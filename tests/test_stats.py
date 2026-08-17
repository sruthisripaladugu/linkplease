import pytest
import asyncio
from app.db import (
    enqueue_dm_job,
    update_job_after_send,
    update_job_reconciliation_result,
    increment_duplicates_blocked,
    get_stats_data
)


@pytest.mark.asyncio
async def test_stats_accuracy_under_concurrent_updates(temp_db):
    # Concurrently enqueue jobs, increment blocked duplicates, update delivered and failed
    async def task_a():
        for i in range(10):
            job_id = await enqueue_dm_job(
                user_id=f"usr_a_{i}",
                rule_id="rule_1",
                comment_id=f"cmt_a_{i}",
                message="Msg",
                db_path=temp_db
            )
            # 5 become sent
            if i < 5:
                await update_job_after_send(job_id, status="waiting_reconciliation", dm_id=f"dm_a_{i}", db_path=temp_db)
                await update_job_reconciliation_result(job_id, status="sent", db_path=temp_db)
            # 2 fail
            elif i < 7:
                await update_job_after_send(job_id, status="failed", last_error="Max retries", db_path=temp_db)

    async def task_b():
        for _ in range(15):
            await increment_duplicates_blocked(1, db_path=temp_db)

    await asyncio.gather(task_a(), task_b())

    stats = await get_stats_data(db_path=temp_db)
    assert stats["sent"] == 5
    assert stats["failed"] == 2
    assert stats["queued"] == 3  # 10 total - 5 sent - 2 failed = 3 remaining in queued_send
    assert stats["duplicates_blocked"] == 15
