import asyncio
import logging
import random
import time
from typing import Optional
from app.config import settings
from app.db import (
    fetch_next_ready_dm_job,
    update_job_after_send,
    fetch_jobs_needing_reconciliation,
    update_job_reconciliation_result
)
from app.rate_limiter import outbound_rate_limiter
from app.pseudogram_client import PseudoGramClient

logger = logging.getLogger(__name__)


class BackgroundWorkerManager:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self.client = PseudoGramClient()
        self._running = False
        self._outbox_task: Optional[asyncio.Task] = None
        self._reconciliation_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._outbox_task = asyncio.create_task(self._outbox_loop(), name="dm_outbox_worker")
        self._reconciliation_task = asyncio.create_task(self._reconciliation_loop(), name="dm_reconciliation_worker")
        logger.info("Background workers (Outbox + Reconciliation) started.")

    async def stop(self) -> None:
        self._running = False
        if self._outbox_task:
            self._outbox_task.cancel()
        if self._reconciliation_task:
            self._reconciliation_task.cancel()
        await self.client.close()
        logger.info("Background workers stopped.")

    async def _outbox_loop(self) -> None:
        """
        Continuously polls for queued DM jobs, enforces rate limit (<=10/60s),
        and sends to Mock API.
        """
        while self._running:
            try:
                # 1. Fetch next ready job from database
                job = await fetch_next_ready_dm_job(self.db_path)
                if not job:
                    await asyncio.sleep(settings.WORKER_POLL_INTERVAL_SECONDS)
                    continue

                # 2. Wait for rate limit slot before sending
                await outbound_rate_limiter.acquire()

                # 3. Dispatch POST /v1/dm/send
                logger.info(f"Sending DM for job {job.job_id} (user: {job.user_id}, comment: {job.comment_id})")
                result = await self.client.send_dm(
                    recipient_user_id=job.user_id,
                    message=job.message,
                    comment_id=job.comment_id,
                    idempotency_key=job.idempotency_key
                )

                # 4. Handle result
                if result.success and result.status_code == 202:
                    logger.info(f"Job {job.job_id} accepted by API. dm_id: {result.dm_id}")
                    await update_job_after_send(
                        job_id=job.job_id,
                        status="waiting_reconciliation",
                        dm_id=result.dm_id,
                        db_path=self.db_path
                    )

                elif result.status_code == 429:
                    # Rate limited: pause rate limiter and reschedule job
                    retry_after = result.retry_after or 5.0
                    logger.warning(f"429 Rate Limited on job {job.job_id}. Pausing for {retry_after}s")
                    await outbound_rate_limiter.pause_for(retry_after)
                    await update_job_after_send(
                        job_id=job.job_id,
                        status="queued_send",
                        next_run_at=time.time() + retry_after,
                        retry_increment=0,
                        last_error="429 Rate Limited",
                        db_path=self.db_path
                    )

                elif result.status_code == 400:
                    # Terminal client error (invalid payload)
                    logger.error(f"Job {job.job_id} failed with 400 invalid request: {result.error_detail}")
                    await update_job_after_send(
                        job_id=job.job_id,
                        status="failed",
                        last_error=f"400 Invalid Request: {result.error_detail}",
                        db_path=self.db_path
                    )

                else:
                    # 500 internal error or network error: exponential backoff retry
                    new_retry_count = job.retry_count + 1
                    if new_retry_count <= job.max_retries:
                        backoff = (settings.BASE_RETRY_DELAY_SECONDS * (2 ** job.retry_count)) + random.uniform(0.1, 1.0)
                        logger.warning(
                            f"Job {job.job_id} transient error ({result.error_type}). "
                            f"Retry {new_retry_count}/{job.max_retries} scheduled in {backoff:.2f}s"
                        )
                        await update_job_after_send(
                            job_id=job.job_id,
                            status="queued_send",
                            next_run_at=time.time() + backoff,
                            retry_increment=1,
                            last_error=f"{result.error_type}: {result.error_detail}",
                            db_path=self.db_path
                        )
                    else:
                        logger.error(f"Job {job.job_id} exhausted all {job.max_retries} retries. Marking failed.")
                        await update_job_after_send(
                            job_id=job.job_id,
                            status="failed",
                            retry_increment=1,
                            last_error=f"Exhausted retries: {result.error_type}",
                            db_path=self.db_path
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in outbox loop: {e}", exc_info=True)
                await asyncio.sleep(1.0)

    async def _reconciliation_loop(self) -> None:
        """
        Periodically checks delivery status of accepted DMs (GET /v1/dm/{dm_id}).
        Reads do NOT count against the rate limit.
        """
        while self._running:
            try:
                jobs = await fetch_jobs_needing_reconciliation(limit=10, db_path=self.db_path)
                if not jobs:
                    await asyncio.sleep(settings.RECONCILIATION_INTERVAL_SECONDS)
                    continue

                for job in jobs:
                    if not job.dm_id:
                        continue

                    status_result = await self.client.get_dm_status(job.dm_id)
                    if not status_result.success:
                        logger.warning(f"Reconciliation poll failed for dm_id {job.dm_id}: {status_result.error_detail}")
                        continue

                    if status_result.status == "delivered":
                        logger.info(f"Reconciliation: DM {job.dm_id} (job {job.job_id}) CONFIRMED delivered!")
                        await update_job_reconciliation_result(
                            job_id=job.job_id,
                            status="sent",
                            last_error=None,
                            db_path=self.db_path
                        )

                    elif status_result.status == "failed":
                        logger.warning(f"Reconciliation: DM {job.dm_id} (job {job.job_id}) FAILED on Mock API side.")
                        new_retry_count = job.retry_count + 1
                        if new_retry_count <= job.max_retries:
                            # Re-enqueue to outbox with fresh attempt
                            backoff = (settings.BASE_RETRY_DELAY_SECONDS * (2 ** job.retry_count)) + random.uniform(0.1, 1.0)
                            logger.info(f"Re-enqueuing job {job.job_id} for retry after reconciliation failure.")
                            await update_job_reconciliation_result(
                                job_id=job.job_id,
                                status="queued_send",
                                retry_increment=1,
                                reschedule_delay=backoff,
                                last_error="Downstream delivery failed; retrying",
                                db_path=self.db_path
                            )
                        else:
                            logger.error(f"Job {job.job_id} delivery failed and max retries reached.")
                            await update_job_reconciliation_result(
                                job_id=job.job_id,
                                status="failed",
                                retry_increment=1,
                                last_error="Downstream delivery failed (max retries reached)",
                                db_path=self.db_path
                            )

                    elif status_result.status == "queued":
                        # Still queued on mock API side; check again in next round
                        pass

                await asyncio.sleep(settings.RECONCILIATION_INTERVAL_SECONDS)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in reconciliation loop: {e}", exc_info=True)
                await asyncio.sleep(2.0)


# Global worker instance
worker_manager = BackgroundWorkerManager()
