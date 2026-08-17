import pytest
from unittest.mock import AsyncMock, patch
from app.db import (
    enqueue_dm_job,
    update_job_after_send,
    get_stats_data,
    fetch_jobs_needing_reconciliation,
    update_job_reconciliation_result
)
from app.pseudogram_client import DMStatusResult


@pytest.mark.asyncio
async def test_reconciliation_delivered_transitions_to_sent(temp_db):
    # Enqueue a job
    job_id = await enqueue_dm_job(
        user_id="usr_david",
        rule_id="rule_1",
        comment_id="cmt_david_1",
        message="Hello David",
        db_path=temp_db
    )

    # Simulate Mock API returning 202 Accepted with dm_id
    await update_job_after_send(
        job_id=job_id,
        status="waiting_reconciliation",
        dm_id="dm_test_12345",
        db_path=temp_db
    )

    stats_before = await get_stats_data(db_path=temp_db)
    assert stats_before["queued"] == 1
    assert stats_before["sent"] == 0

    # Simulate reconciliation confirming delivered
    await update_job_reconciliation_result(
        job_id=job_id,
        status="sent",
        db_path=temp_db
    )

    stats_after = await get_stats_data(db_path=temp_db)
    assert stats_after["queued"] == 0
    assert stats_after["sent"] == 1


@pytest.mark.asyncio
async def test_reconciliation_delayed_failure_and_retry(temp_db):
    job_id = await enqueue_dm_job(
        user_id="usr_emma",
        rule_id="rule_2",
        comment_id="cmt_emma_1",
        message="Hello Emma",
        db_path=temp_db
    )

    await update_job_after_send(
        job_id=job_id,
        status="waiting_reconciliation",
        dm_id="dm_failed_later",
        db_path=temp_db
    )

    # Reconciliation finds Mock API marked status='failed' -> re-queue for retry
    await update_job_reconciliation_result(
        job_id=job_id,
        status="queued_send",
        retry_increment=1,
        reschedule_delay=0.1,
        last_error="Downstream delivery failed; retrying",
        db_path=temp_db
    )

    stats_retry = await get_stats_data(db_path=temp_db)
    assert stats_retry["queued"] == 1
    assert stats_retry["failed"] == 0
