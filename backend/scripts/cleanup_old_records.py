"""Periodic cleanup of append-only tables.

Drops rows older than configurable retention windows so the billing
ledger doesn't grow without bound. Designed to be invoked by the
cloude-cleanup systemd timer (see bin/cloude-cleanup.{service,timer})
or manually with `uv run python -m scripts.cleanup_old_records`.

Retention windows are tunable via env vars (all in days):
  CLEANUP_REQUEST_LOG_DAYS        request_logs                 (default 180)
  CLEANUP_USAGE_RECORD_DAYS       usage_records                (default  90)
  CLEANUP_PENDING_BILLING_DAYS    pending_billings (status=dead) (default 7)
  CLEANUP_REDEMPTION_GRACE_DAYS   redemption_codes (issued + expired) (default 7)

The script is idempotent: re-running after a successful run is a no-op.
Pass --dry-run to print the would-be deletes without writing.

Run with:
    cd backend && uv run python -m scripts.cleanup_old_records
    cd backend && uv run python -m scripts.cleanup_old_records --dry-run
"""

import argparse
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.billing_record import BillingRecord
from app.models.pending_billing import PendingBilling
from app.models.redemption_code import RedemptionCode
from app.models.request_log import RequestLog
from app.models.usage import UsageRecord

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cleanup")

# Default retention windows. Production tuning happens via the env vars
# documented at the top of this file; the defaults here are the
# "ship to a brand-new deployment" baseline.
DEFAULT_REQUEST_LOG_DAYS = 180
DEFAULT_USAGE_RECORD_DAYS = 90
DEFAULT_PENDING_BILLING_DAYS = 7
DEFAULT_REDEMPTION_GRACE_DAYS = 7


def _env_int(name: str, default: int) -> int:
    """Read a positive int from env, falling back to default on missing/garbage."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("env %s=%r is not an int; using default %d", name, raw, default)
        return default
    if value < 0:
        logger.warning("env %s=%d is negative; using default %d", name, value, default)
        return default
    return value


def _retention_config() -> dict[str, int]:
    """Collect all retention windows from env vars with defaults."""
    return {
        "request_logs": _env_int("CLEANUP_REQUEST_LOG_DAYS", DEFAULT_REQUEST_LOG_DAYS),
        "usage_records": _env_int("CLEANUP_USAGE_RECORD_DAYS", DEFAULT_USAGE_RECORD_DAYS),
        "pending_billings_dead": _env_int(
            "CLEANUP_PENDING_BILLING_DAYS", DEFAULT_PENDING_BILLING_DAYS
        ),
        "redemption_codes_expired_grace": _env_int(
            "CLEANUP_REDEMPTION_GRACE_DAYS", DEFAULT_REDEMPTION_GRACE_DAYS
        ),
    }


async def _count(db: AsyncSession, stmt) -> int:
    """Run a SELECT COUNT(*) and return the scalar."""
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


async def cleanup(db: AsyncSession, *, dry_run: bool = False) -> dict[str, int]:
    """Delete rows past retention. Returns {table_name: deleted_count}.

    Idempotent: counts are computed first, so a second run after all rows
    are gone deletes zero rows. Wrapped in a single transaction so a
    failure halfway leaves the DB in its prior state.
    """
    cfg = _retention_config()
    now = datetime.now(timezone.utc)

    request_log_cutoff = now - timedelta(days=cfg["request_logs"])
    usage_record_cutoff = now - timedelta(days=cfg["usage_records"])
    pending_billing_cutoff = now - timedelta(days=cfg["pending_billings_dead"])
    redemption_grace_cutoff = now - timedelta(days=cfg["redemption_codes_expired_grace"])

    # Each target is (label, count_select, delete_stmt, retention_days). The
    # count SELECT is built from the same WHERE conditions as the DELETE so
    # the count and the delete always agree; SELECT COUNT(*)-over-DELETE-
    # subquery doesn't work in SQLAlchemy 2.x (Delete has no .subquery()).
    targets: list[tuple[str, object, object, int]] = []

    # 1. request_logs — only delete ones with no billing_record pointing at
    #    them (FK has no ON DELETE CASCADE; deleting would fail otherwise).
    rl_count = select(func.count()).select_from(RequestLog).where(
        RequestLog.created_at < request_log_cutoff,
        ~select(BillingRecord.id).where(BillingRecord.request_log_id == RequestLog.id).exists(),
    )
    rl_delete = (
        delete(RequestLog)
        .where(RequestLog.created_at < request_log_cutoff)
        .where(
            ~select(BillingRecord.id).where(BillingRecord.request_log_id == RequestLog.id).exists()
        )
    )
    targets.append(("request_logs", rl_count, rl_delete, cfg["request_logs"]))

    # 2. usage_records — independent, no FK back to request_logs.
    ur_count = select(func.count()).select_from(UsageRecord).where(
        UsageRecord.created_at < usage_record_cutoff
    )
    ur_delete = delete(UsageRecord).where(UsageRecord.created_at < usage_record_cutoff)
    targets.append(("usage_records", ur_count, ur_delete, cfg["usage_records"]))

    # 3. pending_billings — only `dead` rows past grace. `pending` and
    #    `settled` rows are still live data and must not be deleted.
    pb_count = select(func.count()).select_from(PendingBilling).where(
        PendingBilling.status == "dead",
        PendingBilling.created_at < pending_billing_cutoff,
    )
    pb_delete = delete(PendingBilling).where(
        PendingBilling.status == "dead",
        PendingBilling.created_at < pending_billing_cutoff,
    )
    targets.append(("pending_billings (dead)", pb_count, pb_delete, cfg["pending_billings_dead"]))

    # 4. redemption_codes — `issued` codes whose `expires_at` passed >grace
    #    days ago. `used` codes stay forever (they're the audit trail of
    #    who redeemed what). `expired` status is not auto-set; this delete
    #    is the cleanup that matters.
    rc_count = select(func.count()).select_from(RedemptionCode).where(
        RedemptionCode.status == "issued",
        RedemptionCode.expires_at < redemption_grace_cutoff,
    )
    rc_delete = delete(RedemptionCode).where(
        RedemptionCode.status == "issued",
        RedemptionCode.expires_at < redemption_grace_cutoff,
    )
    targets.append(
        (
            "redemption_codes (issued+expired)",
            rc_count,
            rc_delete,
            cfg["redemption_codes_expired_grace"],
        )
    )

    summary: dict[str, int] = {}
    for label, count_stmt, delete_stmt, days in targets:
        count = int((await db.execute(count_stmt)).scalar() or 0)
        if dry_run:
            logger.info(
                "[dry-run] %s: would delete %d rows (retention=%d days)",
                label,
                count,
                days,
            )
            summary[label] = 0
            continue
        if count == 0:
            logger.info("%s: 0 rows past retention; skipping", label)
            summary[label] = 0
            continue
        result = await db.execute(delete_stmt)
        summary[label] = count
        logger.info(
            "%s: deleted %d rows (retention=%d days, rowcount=%s)",
            label,
            count,
            days,
            result.rowcount,
        )

    if dry_run:
        await db.rollback()
    else:
        await db.commit()
    return summary


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count rows that would be deleted, but do not delete or commit.",
    )
    args = parser.parse_args()

    cfg = _retention_config()
    logger.info("retention windows (days): %s", cfg)
    logger.info("dry-run=%s", args.dry_run)

    engine = create_async_engine(settings.database_url)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as db:
            summary = await cleanup(db, dry_run=args.dry_run)
    finally:
        await engine.dispose()

    total = sum(summary.values())
    logger.info("done. total deleted: %d (dry-run=%s)", total, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
