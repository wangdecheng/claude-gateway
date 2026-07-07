#!/usr/bin/env python3
"""sync_from_remote.py — Pull platform-config tables from remote PG into local SQLite.

This is a one-shot developer tool, not part of the runtime. It is safe to
re-run: it wipes the local config tables (providers / provider_keys /
channels / models / model_provider_routes / token_coefficients) and
re-fills them from a fresh pg_dump over SSH.

User data (users, api_keys, payments, billing_records, request_logs,
usage_logs, redemption_codes, pending_billing) is NEVER touched.

Usage:
  scripts/sync_from_remote.py                              # sync everything
  scripts/sync_from_remote.py --dry-run                    # only dump + parse
  scripts/sync_from_remote.py --tables providers,channels  # subset
  scripts/sync_from_remote.py --ssh-host user@host         # override SSH target
  scripts/sync_from_remote.py --ssh-key /path/key          # override SSH key
  scripts/sync_from_remote.py --remote-pg-host 10.0.0.1    # override PG host
  scripts/sync_from_remote.py --remote-pg-port 5433        # override PG port
  scripts/sync_from_remote.py --remote-pg-user foo         # override PG user
  scripts/sync_from_remote.py --remote-pg-password bar     # override PG password
  scripts/sync_from_remote.py --remote-pg-db mydb          # override PG db

Env vars (all optional):
  DEPLOY_REMOTE              ssh destination (default root@47.103.206.6)
  DEPLOY_SSH_KEY             ssh key (default ~/ai/aliyun-ai01.pem)
  REMOTE_PG_HOST             default 127.0.0.1
  REMOTE_PG_PORT             default 5432
  REMOTE_PG_USER             default high_api
  REMOTE_PG_PASSWORD         default high_api_dev
  REMOTE_PG_DB               default high_api
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Allow running this file directly (no __init__.py in scripts/) and from
# elsewhere via `python -m` style imports of sibling modules.
sys.path.insert(0, str(Path(__file__).resolve().parent))
# Make backend/app importable (where app.config + app.database live).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from _sync_parser import parse_dump  # noqa: E402
from _sync_remap import IdRemap, SyncReport  # noqa: E402


# ── Defaults (mirrors bin/deploy.sh + remote backend/.env DATABASE_URL) ─
DEFAULT_SSH_HOST = "root@47.103.206.6"
DEFAULT_SSH_KEY = os.path.expanduser("~/ai/aliyun-ai01.pem")
DEFAULT_REMOTE_PG_HOST = "127.0.0.1"
DEFAULT_REMOTE_PG_PORT = "5432"
DEFAULT_REMOTE_PG_USER = "high_api"
DEFAULT_REMOTE_PG_PASSWORD = "high_api_dev"
DEFAULT_REMOTE_PG_DB = "high_api"
DEFAULT_TABLES = [
    "providers",
    "provider_keys",
    "channels",
    "models",
    "model_provider_routes",
    "token_coefficients",
]


def dump_remote_tables(
    *,
    ssh_host: str,
    ssh_key: str,
    pg_host: str,
    pg_port: str,
    pg_user: str,
    pg_password: str,
    pg_db: str,
    tables: list[str],
) -> str:
    """Run pg_dump on the remote over SSH and return the SQL text."""
    if not Path(ssh_key).exists():
        raise SystemExit(f"SSH key not found: {ssh_key} (set DEPLOY_SSH_KEY)")

    table_args = " ".join(f"-t {shlex.quote(t)}" for t in tables)
    remote_cmd = (
        f"PGPASSWORD={shlex.quote(pg_password)} "
        f"pg_dump -h {shlex.quote(pg_host)} -p {shlex.quote(pg_port)} "
        f"-U {shlex.quote(pg_user)} -d {shlex.quote(pg_db)} "
        f"--data-only --inserts --no-owner --no-privileges {table_args}"
    )
    ssh = ["ssh", "-i", ssh_key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
           ssh_host, remote_cmd]

    print(f"[sync] dumping {len(tables)} tables from {ssh_host}:{pg_host}:{pg_port}/{pg_db} ...")
    proc = subprocess.run(ssh, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(
            f"remote pg_dump failed (rc={proc.returncode}):\n"
            f"  stdout: {proc.stdout[-500:]}\n"
            f"  stderr: {proc.stderr[-500:]}"
        )
    if not proc.stdout.strip():
        raise SystemExit(
            f"remote pg_dump returned empty output — is the remote PG reachable "
            f"at {pg_host}:{pg_port} as {pg_user}/{pg_db}?"
        )
    return proc.stdout


def write_dump_to_tempfile(sql: str) -> Path:
    """Write dump to a tempfile in /tmp and return its path."""
    fd, path = tempfile.mkstemp(prefix="claude-sync-dump-", suffix=".sql", dir="/tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(sql)
    except Exception:
        os.unlink(path)
        raise
    return Path(path)


def fetch_remote_columns(
    *,
    ssh_host: str,
    ssh_key: str,
    pg_host: str,
    pg_port: str,
    pg_user: str,
    pg_password: str,
    pg_db: str,
    tables: list[str],
) -> dict[str, list[str]]:
    """Query remote information_schema for each table's column order.

    Returns {table_name: [col_name, ...]} in remote ordinal_position order.
    Output is parsed from psql -t -A tuples (table|col).
    """
    if not Path(ssh_key).exists():
        raise SystemExit(f"SSH key not found: {ssh_key}")

    table_list = ",".join(f"'{t}'" for t in tables)
    sql = (
        "SELECT table_name, column_name FROM information_schema.columns "
        f"WHERE table_name IN ({table_list}) "
        "ORDER BY table_name, ordinal_position;"
    )
    remote_cmd = (
        f"PGPASSWORD={shlex.quote(pg_password)} "
        f"psql -h {shlex.quote(pg_host)} -p {shlex.quote(pg_port)} "
        f"-U {shlex.quote(pg_user)} -d {shlex.quote(pg_db)} -t -A -F '|' -c {shlex.quote(sql)}"
    )
    ssh = ["ssh", "-i", ssh_key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
           ssh_host, remote_cmd]
    proc = subprocess.run(ssh, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(
            f"remote column query failed (rc={proc.returncode}):\n"
            f"  stderr: {proc.stderr[-500:]}"
        )

    cols: dict[str, list[str]] = {t: [] for t in tables}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        tbl, col = line.split("|", 1)
        cols.setdefault(tbl.strip(), []).append(col.strip())
    return cols


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Sync platform-config tables from remote PG into local SQLite.",
    )
    p.add_argument("--dry-run", action="store_true",
                   help="Dump + parse only; do not modify local DB.")
    p.add_argument("--tables", default=",".join(DEFAULT_TABLES),
                   help=f"Comma-separated tables (default: {','.join(DEFAULT_TABLES)})")
    p.add_argument("--ssh-host", default=os.environ.get("DEPLOY_REMOTE", DEFAULT_SSH_HOST))
    p.add_argument("--ssh-key", default=os.environ.get("DEPLOY_SSH_KEY", DEFAULT_SSH_KEY))
    p.add_argument("--remote-pg-host",
                   default=os.environ.get("REMOTE_PG_HOST", DEFAULT_REMOTE_PG_HOST))
    p.add_argument("--remote-pg-port",
                   default=os.environ.get("REMOTE_PG_PORT", DEFAULT_REMOTE_PG_PORT))
    p.add_argument("--remote-pg-user",
                   default=os.environ.get("REMOTE_PG_USER", DEFAULT_REMOTE_PG_USER))
    p.add_argument("--remote-pg-password",
                   default=os.environ.get("REMOTE_PG_PASSWORD", DEFAULT_REMOTE_PG_PASSWORD))
    p.add_argument("--remote-pg-db",
                   default=os.environ.get("REMOTE_PG_DB", DEFAULT_REMOTE_PG_DB))
    return p


# ── Async DB layer (Task 4) ───────────────────────────────────────────

# Column remap tables: which columns in each table need provider_id / model_id
# substitution, and which column is the PK that gets a fresh local id.
_COL_REMAP: dict[str, dict] = {
    "providers":              {"pk": "id", "use_remap": {}},
    "models":                 {"pk": "id", "use_remap": {}},
    "provider_keys":          {"pk": "id", "use_remap": {"provider_id": "provider"}},
    "channels":               {"pk": "id", "use_remap": {
                                  "provider_id": "provider",
                                  "model_id": "model",
                              }},
    "model_provider_routes":  {"pk": "id", "use_remap": {
                                  "provider_id": "provider",
                                  "model_id": "model",
                              }},
    "token_coefficients":     {"pk": "id", "use_remap": {"model_id": "model"}},
}


async def collect_local_max_ids() -> dict[str, int]:
    """Query local DB for MAX(id) per config table. Returns {} for empty/missing tables."""
    from sqlalchemy import text
    from app.config import settings
    from app.database import create_async_engine_and_sessionmaker

    engine, session_factory = create_async_engine_and_sessionmaker(settings.database_url)
    result: dict[str, int] = {}
    async with engine.begin() as conn:
        for table in DEFAULT_TABLES:
            try:
                row = await conn.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table}"))
                result[table] = int(row.scalar_one())
            except Exception:
                # Table may not exist yet (fresh DB); start from 0
                result[table] = 0
    await engine.dispose()
    return result


async def wipe_local_providers() -> None:
    """Delete all 6 config tables in reverse FK dependency order.

    Idempotent: safe to call on empty tables. Wiping model_provider_routes
    first unblocks providers (which has FKs from pending_billing/usage/
    request_log via model_provider_routes on the real PG schema).

    Each DELETE runs in its own transaction (separate engine.begin()) so a
    single failure (e.g. missing table) doesn't poison the rest.
    """
    from sqlalchemy import text
    from app.config import settings
    from app.database import create_async_engine_and_sessionmaker

    engine, _ = create_async_engine_and_sessionmaker(settings.database_url)
    for table in reversed(DEFAULT_TABLES):
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f"DELETE FROM {table}"))
        except Exception:
            # Table may not exist locally yet, or FK violation — skip.
            pass
    await engine.dispose()


async def insert_local_rows(
    table: str, rows: list[list], remap: IdRemap, report: SyncReport,
    remote_cols: list[str],
) -> None:
    """Insert parsed rows into local DB.

    For 'providers' / 'models': assign new local id, store in remap.
    For dependent tables: rewrite provider_id / model_id columns using remap.

    `remote_cols` is the list of column names in the order they appear in each
    parsed `rows[i]` (i.e. the order pg_dump --inserts emits them in).
    """
    from datetime import datetime
    from sqlalchemy import text
    from app.config import settings
    from app.database import create_async_engine_and_sessionmaker

    if table not in _COL_REMAP:
        report.add(table, inserted=0, skipped=0, failed=len(rows))
        report.note_skip(table, "no _COL_REMAP entry; table skipped")
        return

    cfg = _COL_REMAP[table]

    # First pass: figure out column names by introspecting the local table,
    # then build a remote-position -> local-position map.
    engine, session_factory = create_async_engine_and_sessionmaker(settings.database_url)
    try:
        async with engine.begin() as conn:
            col_rows = await conn.execute(text(
                "SELECT column_name, ordinal_position, data_type FROM information_schema.columns "
                "WHERE table_name = :t ORDER BY ordinal_position"
            ), {"t": table})
            rows_meta = col_rows.fetchall()
            local_cols = [r[0] for r in rows_meta]
            local_types = {r[0]: r[2] for r in rows_meta}
        if not local_cols:
            report.add(table, inserted=0, skipped=0, failed=len(rows))
            report.note_skip(table, "table does not exist locally; run alembic upgrade head")
            return

        # Determine which local columns need datetime conversion (timestamp variants).
        ts_cols = {
            c for c, dt in local_types.items()
            if "timestamp" in dt or "datetime" in dt
        }

        # Build map: for each remote column (positional), find its local index.
        # Columns present in remote but missing locally are dropped.
        # Columns missing in remote but present locally are filled with None.
        remote_to_local: list[int | None] = []
        for rcol in remote_cols:
            if rcol in local_cols:
                remote_to_local.append(local_cols.index(rcol))
            else:
                remote_to_local.append(None)

        # Local-position -> kind for provider_id / model_id remapping
        local_remap_idx: dict[int, str] = {}  # local_idx -> "provider" | "model"
        for col_name, kind in cfg["use_remap"].items():
            if col_name in local_cols:
                local_remap_idx[local_cols.index(col_name)] = kind

        for raw_row in rows:
            # Project remote row into local column order
            local_row: list = [None] * len(local_cols)
            for r_idx, value in enumerate(raw_row):
                l_idx = remote_to_local[r_idx] if r_idx < len(remote_to_local) else None
                if l_idx is None:
                    continue
                lcol = local_cols[l_idx]
                # Convert timestamp strings → datetime for asyncpg
                if lcol in ts_cols and isinstance(value, str) and value:
                    try:
                        value = datetime.fromisoformat(value.replace(" ", "T"))
                    except ValueError:
                        pass
                local_row[l_idx] = value

            # Assign fresh local id (using local_pk index)
            pk_col = cfg["pk"]
            pk_idx = local_cols.index(pk_col)
            if table == "providers":
                new_id = remap.next_provider_id(remote_id=local_row[pk_idx])
                local_row[pk_idx] = new_id
            elif table == "models":
                new_id = remap.next_model_id(remote_id=local_row[pk_idx])
                local_row[pk_idx] = new_id
            else:
                # remote id is meaningless locally; let PG sequence assign.
                local_row[pk_idx] = None

            # Apply id remap to provider_id / model_id columns (by LOCAL idx)
            skip_row = False
            raw_pk = raw_row[0] if raw_row else None
            for l_idx, kind in local_remap_idx.items():
                remote_id = local_row[l_idx]
                if remote_id is None:
                    continue
                if kind == "provider":
                    if remote_id not in remap.provider_ids:
                        report.note_skip(table, f"row pk={raw_pk}: unknown provider_id={remote_id}")
                        skip_row = True
                        break
                    local_row[l_idx] = remap.provider_ids[remote_id]
                elif kind == "model":
                    if remote_id not in remap.model_ids:
                        report.note_skip(table, f"row pk={raw_pk}: unknown model_id={remote_id}")
                        skip_row = True
                        break
                    local_row[l_idx] = remap.model_ids[remote_id]

            if skip_row:
                report.add(table, inserted=0, skipped=1, failed=0)
                continue

            # All remap lookups succeeded; try the INSERT in its own txn so a
            # single failure doesn't poison subsequent rows.
            # For non-root tables we omit the PK column so the PG sequence
            # DEFAULT fires (passing literal NULL bypasses the default).
            if table in ("providers", "models"):
                insert_cols = local_cols
                insert_row = local_row
            else:
                insert_cols = [c for i, c in enumerate(local_cols) if i != pk_idx]
                insert_row = [v for i, v in enumerate(local_row) if i != pk_idx]
            placeholders = ", ".join(f":p{i}" for i in range(len(insert_cols)))
            col_list = ", ".join(f'"{c}"' for c in insert_cols)
            try:
                async with engine.begin() as conn:
                    await conn.execute(
                        text(f'INSERT INTO {table} ({col_list}) VALUES ({placeholders})'),
                        {f"p{i}": v for i, v in enumerate(insert_row)},
                    )
                report.add(table, inserted=1, skipped=0, failed=0)
            except Exception as e:
                report.add(table, inserted=0, skipped=0, failed=1)
                report.note_skip(table, f"row pk={raw_pk}: {type(e).__name__}: {str(e)[:200]}")
    finally:
        await engine.dispose()


async def reset_sqlite_sequences() -> None:
    """Reset sqlite_sequence so autoincrement picks up after MAX(id)."""
    from sqlalchemy import text
    from app.config import settings
    from app.database import create_async_engine_and_sessionmaker

    if not settings.database_url.startswith("sqlite"):
        return

    engine, _ = create_async_engine_and_sessionmaker(settings.database_url)
    try:
        async with engine.begin() as conn:
            for table in DEFAULT_TABLES:
                # Re-set seq to current MAX(id) for each table
                await conn.execute(text(
                    f"UPDATE sqlite_sequence SET seq = (SELECT MAX(id) FROM {table}) "
                    f"WHERE name = :t"
                ), {"t": table})
    finally:
        await engine.dispose()


async def main_async(args: argparse.Namespace) -> int:
    from app.config import settings
    report = SyncReport()
    report.start_time = time.time()

    tables = [t.strip() for t in args.tables.split(",") if t.strip()]
    sql = dump_remote_tables(
        ssh_host=args.ssh_host,
        ssh_key=args.ssh_key,
        pg_host=args.remote_pg_host,
        pg_port=args.remote_pg_port,
        pg_user=args.remote_pg_user,
        pg_password=args.remote_pg_password,
        pg_db=args.remote_pg_db,
        tables=tables,
    )
    dump_path = write_dump_to_tempfile(sql)
    print(f"[sync] dump written to {dump_path} ({len(sql)} bytes)")

    try:
        parsed = parse_dump(sql)
        print(f"[sync] parsed: {', '.join(f'{t}={len(rows)}' for t, rows in parsed.items())}")

        if args.dry_run:
            print("[sync] --dry-run: skipping local DB write")
            return 0

        # Query remote column order (needed because local + remote schemas can
        # have different column ordering; pg_dump emits values in remote order).
        remote_columns = fetch_remote_columns(
            ssh_host=args.ssh_host,
            ssh_key=args.ssh_key,
            pg_host=args.remote_pg_host,
            pg_port=args.remote_pg_port,
            pg_user=args.remote_pg_user,
            pg_password=args.remote_pg_password,
            pg_db=args.remote_pg_db,
            tables=tables,
        )

        # Local DB work (Task 4)
        max_ids = await collect_local_max_ids()
        remap = IdRemap(
            start_provider_id=max_ids.get("providers", 0) + 1,
            start_model_id=max_ids.get("models", 0) + 1,
        )

        await wipe_local_providers()
        print("[sync] local providers wiped (FK cascade cleared provider_keys + channels)")

        # providers — must come first; sets up provider_ids remap
        if "providers" in parsed:
            await insert_local_rows(
                "providers", parsed["providers"], remap, report,
                remote_cols=remote_columns.get("providers", []),
            )

        # models — second; sets up model_ids remap
        if "models" in parsed:
            await insert_local_rows(
                "models", parsed["models"], remap, report,
                remote_cols=remote_columns.get("models", []),
            )

        # dependent tables — order matters
        for t in ("provider_keys", "channels", "model_provider_routes", "token_coefficients"):
            if t in parsed:
                await insert_local_rows(
                    t, parsed[t], remap, report,
                    remote_cols=remote_columns.get(t, []),
                )

        await reset_sqlite_sequences()
        if settings.database_url.startswith("sqlite"):
            print("[sync] sqlite_sequence reset")
    finally:
        os.unlink(dump_path)
        print(f"[sync] dump cleaned: {dump_path}")

    report.end_time = time.time()
    print()
    print(report.render())
    return report.exit_code()


def main() -> int:
    args = build_argparser().parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())