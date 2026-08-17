import pytest
from app.db import get_stats_data


@pytest.mark.asyncio
async def test_user_never_dmed_twice_for_same_rule(client, temp_db):
    # 1. Create a rule
    rule_res = await client.post("/rules", json={"keyword": "PRICE", "dm_message": "Price list here"})
    assert rule_res.status_code == 201

    # 2. First comment from usr_alice
    await client.post("/webhook", json={
        "event_id": "evt_alice_1",
        "event_type": "comment.created",
        "data": {
            "comment_id": "cmt_alice_1",
            "text": "What is the price?",
            "from": {"user_id": "usr_alice", "username": "alice"}
        }
    })

    stats1 = await client.get("/stats")
    assert stats1.json()["queued"] == 1
    assert stats1.json()["duplicates_blocked"] == 0

    # 3. Second comment from usr_alice on another post or same post with matching keyword
    await client.post("/webhook", json={
        "event_id": "evt_alice_2",
        "event_type": "comment.created",
        "data": {
            "comment_id": "cmt_alice_2",
            "text": "Hey PRICE please again!",
            "from": {"user_id": "usr_alice", "username": "alice"}
        }
    })

    stats2 = await client.get("/stats")
    # Queued count should still be 1 (not 2!), duplicates_blocked should be 1
    assert stats2.json()["queued"] == 1
    assert stats2.json()["duplicates_blocked"] == 1

    # 4. Third comment from usr_bob (different user)
    await client.post("/webhook", json={
        "event_id": "evt_bob_1",
        "event_type": "comment.created",
        "data": {
            "comment_id": "cmt_bob_1",
            "text": "Price info?",
            "from": {"user_id": "usr_bob", "username": "bob"}
        }
    })

    stats3 = await client.get("/stats")
    assert stats3.json()["queued"] == 2
    assert stats3.json()["duplicates_blocked"] == 1
