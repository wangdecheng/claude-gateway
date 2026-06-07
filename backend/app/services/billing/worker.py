"""Background worker — scans pending_billing and settles each row."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.pending_billing import PendingBilling
from app.services.billing.pending import claim_pending_batch
from app.services.billing.settle import mark_retry, max_retry_reached, settle_one

logger = logging.getLogger("cloude-gateway.billing.worker")


class BillingWorker:
    """In-process asyncio task that settles pending_billing rows.

    Run one per app instance. Uses FOR UPDATE SKIP LOCKED so that multi-worker
    setups are safe (each instance claims a disjoint batch).
    """

    def __init__(
        self,
        session_factory: async_sessionmaker,
        *,
        scan_interval: int = 30,
        max_age_seconds: int = 5,
        max_retry: int = 3,
        batch_limit: int = 100,
    ) -> None:
        self.session_factory = session_factory
        self.scan_interval = scan_interval
        self.max_age_seconds = max_age_seconds
        self.max_retry = max_retry
        self.batch_limit = batch_limit
        self._task: asyncio.Task | None = None
        self._stopped = False

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopped = False
        self._task = asyncio.create_task(self._run_loop(), name="billing-worker")

    async def stop(self) -> None:
        self._stopped = True
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run_loop(self) -> None:
        while not self._stopped:
            try:
                await self._scan_and_settle()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("BillingWorker scan failed; will retry next interval")
            try:
                await asyncio.sleep(self.scan_interval)
            except asyncio.CancelledError:
                raise

    async def _scan_and_settle(self) -> int:
        """Claim a batch and settle each row in its own short transaction.

        Returns the number of rows successfully settled.
        """
        # Phase 1: claim batch inside a short transaction
        async with self.session_factory() as db:
            claimed = await claim_pending_batch(
                db,
                max_age_seconds=self.max_age_seconds,
                limit=self.batch_limit,
            )
            claimed_ids = [pb.id for pb in claimed]
            await db.commit()  # release FOR UPDATE locks

        if not claimed_ids:
            return 0

        # Phase 2: settle each row independently
        settled_count = 0
        for pb_id in claimed_ids:
            try:
                async with self.session_factory() as db:
                    pb = await db.get(PendingBilling, pb_id)
                    if pb is None or pb.status != "pending":
                        continue
                    await settle_one(db, pb)
                    await db.commit()
                settled_count += 1
            except Exception as exc:
                logger.exception("settle_one failed for %s", pb_id)
                try:
                    async with self.session_factory() as db:
                        pb = await db.get(PendingBilling, pb_id)
                        if pb is None:
                            continue
                        await mark_retry(db, pb, exc)
                        if max_retry_reached(pb, self.max_retry):
                            pb.status = "dead"
                            logger.error("PendingBilling %s marked dead after %d retries", pb_id, pb.retry_count)
                        await db.commit()
                except Exception:
                    logger.exception("mark_retry also failed for %s", pb_id)
        return settled_count
