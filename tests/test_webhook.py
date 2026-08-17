import json
import pytest
from app.config import settings
from app.security import generate_webhook_signature


@pytest.mark.asyncio
async def test_webhook_hmac_signature_validation(client):
    secret = "test_secret_key_123"
    settings.API_KEY = secret
    settings.ENFORCE_WEBHOOK_SIGNATURE = True

    payload = {
        "event_id": "evt_sig_test_1",
        "event_type": "comment.created",
        "sent_at": "2026-08-10T09:14:22.481Z",
        "data": {
            "comment_id": "cmt_100",
            "post_id": "post_100",
            "text": "PRICE please",
            "created_at": "2026-08-10T09:14:21.900Z",
            "from": {"user_id": "usr_100", "username": "user100"}
        }
    }
    raw_body = json.dumps(payload).encode("utf-8")

    # 1. Invalid signature should be rejected with 401
    res_bad = await client.post(
        "/webhook",
        content=raw_body,
        headers={"X-PseudoGram-Signature": "sha256=invalidhex123"}
    )
    assert res_bad.status_code == 401

    # 2. Valid signature should be accepted with 200
    valid_sig = generate_webhook_signature(raw_body, secret)
    res_ok = await client.post(
        "/webhook",
        content=raw_body,
        headers={"X-PseudoGram-Signature": valid_sig}
    )
    assert res_ok.status_code == 200

    # Reset settings
    settings.API_KEY = ""
    settings.ENFORCE_WEBHOOK_SIGNATURE = False


@pytest.mark.asyncio
async def test_webhook_duplicate_event_id_idempotency(client):
    payload = {
        "event_id": "evt_duplicate_999",
        "event_type": "comment.created",
        "sent_at": "2026-08-10T09:14:22.481Z",
        "data": {
            "comment_id": "cmt_999",
            "post_id": "post_999",
            "text": "PRICE",
            "from": {"user_id": "usr_999", "username": "user999"}
        }
    }

    # First delivery
    res1 = await client.post("/webhook", json=payload)
    assert res1.status_code == 200

    # Second delivery (same event_id)
    res2 = await client.post("/webhook", json=payload)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2.get("status") == "duplicate_event_acknowledged"
