import pytest
from app.db import get_stats_data, fetch_jobs_needing_reconciliation, get_db


@pytest.mark.asyncio
async def test_comment_deleted_cancels_pending_dm(client, temp_db):
    # 1. Create a rule
    await client.post("/rules", json={"keyword": "INFO", "dm_message": "Here is info"})

    # 2. Comment created event arrives
    await client.post("/webhook", json={
        "event_id": "evt_c1",
        "event_type": "comment.created",
        "data": {
            "comment_id": "cmt_to_delete",
            "text": "Send INFO please",
            "from": {"user_id": "usr_charlie", "username": "charlie"}
        }
    })

    stats1 = await client.get("/stats")
    assert stats1.json()["queued"] == 1

    # 3. User deletes the comment before DM is sent
    del_res = await client.post("/webhook", json={
        "event_id": "evt_c2",
        "event_type": "comment.deleted",
        "data": {
            "comment_id": "cmt_to_delete"
        }
    })
    assert del_res.status_code == 200

    # Verify job status changed to 'cancelled' in DB
    async with get_db(temp_db) as db:
        cursor = await db.execute("SELECT status FROM dm_jobs WHERE comment_id = 'cmt_to_delete'")
        row = await cursor.fetchone()
        assert row["status"] == "cancelled"

    # Queued count should now be 0
    stats2 = await client.get("/stats")
    assert stats2.json()["queued"] == 0
