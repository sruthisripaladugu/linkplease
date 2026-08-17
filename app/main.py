import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, status, Header, Depends
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from typing import Optional, Dict, Any, List

from app.config import settings
from app.models import (
    CreateRuleRequest,
    RuleResponse,
    WebhookEvent,
    StatsResponse,
)
from app.db import (
    init_db,
    create_rule,
    get_all_rules,
    get_matching_rules,
    record_event,
    reserve_user_rule_delivery,
    increment_duplicates_blocked,
    enqueue_dm_job,
    cancel_pending_jobs_for_comment,
    get_stats_data,
    get_recent_activity
)
from app.security import verify_webhook_signature
from app.worker import worker_manager
from app.pseudogram_client import PseudoGramClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("linkplease")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing SQLite database...")
    await init_db()
    logger.info("Starting background worker loops...")
    await worker_manager.start()
    yield
    # Shutdown
    logger.info("Shutting down background workers...")
    await worker_manager.stop()


app = FastAPI(
    title="LinkPlease DM Automation Service",
    description="Production Instagram DM Automation handling hostile API conditions.",
    version="1.0.0",
    lifespan=lifespan
)


# --- Core Required API Contract ---

@app.post("/rules", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule_endpoint(req: CreateRuleRequest):
    """
    Creates a new keyword trigger rule.
    Returns 201 Created with rule_id, keyword, dm_message.
    """
    if not req.keyword.strip() or not req.dm_message.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="keyword and dm_message must not be empty."
        )

    rule = await create_rule(keyword=req.keyword.strip(), dm_message=req.dm_message.strip())
    logger.info(f"Rule created: {rule.rule_id} for keyword='{rule.keyword}'")
    return rule


@app.get("/rules", response_model=List[RuleResponse])
async def list_rules_endpoint():
    """Lists all configured rules."""
    return await get_all_rules()


@app.post("/webhook")
async def webhook_endpoint(
    request: Request,
    x_pseudogram_signature: Optional[str] = Header(None, alias="X-PseudoGram-Signature")
):
    """
    Receives comment events. Returns 200 OK within 5 seconds.
    Verifies HMAC-SHA256 signature, deduplicates events, and queues DM jobs asynchronously.
    """
    raw_body = await request.body()

    # Part B: Webhook Signature Verification
    if settings.API_KEY or settings.ENFORCE_WEBHOOK_SIGNATURE:
        is_valid = verify_webhook_signature(
            raw_body=raw_body,
            signature_header=x_pseudogram_signature,
            secret_key=settings.API_KEY
        )
        if not is_valid:
            logger.warning("Rejected webhook due to invalid HMAC signature.")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "invalid_signature", "detail": "HMAC-SHA256 signature verification failed."}
            )

    try:
        payload_dict = json.loads(raw_body.decode("utf-8"))
        event = WebhookEvent(**payload_dict)
    except Exception as e:
        logger.error(f"Malformed webhook payload: {e}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "invalid_payload", "detail": str(e)}
        )

    # 1. Event Idempotency Check (handles ~8% duplicate redeliveries)
    is_new = await record_event(
        event_id=event.event_id,
        event_type=event.event_type,
        comment_id=event.data.comment_id,
        post_id=event.data.post_id,
        user_id=event.data.from_.user_id if event.data.from_ else None,
        username=event.data.from_.username if event.data.from_ else None,
        text=event.data.text,
        sent_at=event.sent_at
    )

    if not is_new:
        logger.info(f"Duplicate event_id '{event.event_id}' ignored.")
        return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "duplicate_event_acknowledged"})

    # 2. Handle comment.deleted (Part C)
    if event.event_type == "comment.deleted":
        cancelled = await cancel_pending_jobs_for_comment(event.data.comment_id)
        logger.info(f"Handled comment.deleted for '{event.data.comment_id}', cancelled {cancelled} pending jobs.")
        return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "comment_deleted_processed", "cancelled_jobs": cancelled})

    # 3. Handle comment.created
    if event.event_type == "comment.created":
        comment_text = event.data.text or ""
        user_id = event.data.from_.user_id if event.data.from_ else None
        comment_id = event.data.comment_id

        if not user_id:
            logger.warning(f"Comment {comment_id} missing user_id; skipping rule match.")
            return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "missing_user_id"})

        # Match against active rules (case-insensitive substring)
        matching_rules = await get_matching_rules(comment_text)

        for rule in matching_rules:
            # Atomic deduplication per (user_id, rule_id)
            reserved = await reserve_user_rule_delivery(
                user_id=user_id,
                rule_id=rule.rule_id,
                comment_id=comment_id
            )

            if reserved:
                # First time this user matched this rule -> enqueue DM
                job_id = await enqueue_dm_job(
                    user_id=user_id,
                    rule_id=rule.rule_id,
                    comment_id=comment_id,
                    message=rule.dm_message,
                    max_retries=settings.MAX_RETRIES
                )
                logger.info(f"Queued DM job {job_id} for user {user_id} on rule '{rule.keyword}'")
            else:
                # User already DMed for this rule -> block duplicate
                await increment_duplicates_blocked(1)
                logger.info(f"Blocked duplicate DM: user {user_id} already received DM for rule {rule.rule_id}")

    return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ok"})


@app.get("/stats", response_model=StatsResponse)
async def stats_endpoint():
    """
    Returns accurate live statistics:
    - sent: DMs confirmed delivered by Mock API
    - failed: DMs given up after retries or terminal failure
    - queued: DMs waiting to send, in-flight, or waiting reconciliation
    - duplicates_blocked: DMs correctly blocked by deduplication
    """
    stats_data = await get_stats_data()
    return StatsResponse(**stats_data)


# --- Helper / Operational Endpoints ---

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "linkplease"}


@app.get("/api/activity")
async def activity_endpoint(limit: int = 50):
    """Returns recent events and DM job activity for dashboard visualization."""
    return await get_recent_activity(limit=limit)


@app.post("/api/simulate/start")
async def simulate_start_endpoint(req: Dict[str, Any]):
    """Proxy helper to trigger Mock API simulation."""
    webhook_url = req.get("webhook_url")
    count = int(req.get("count", 500))
    duration_seconds = int(req.get("duration_seconds", 10))
    client = PseudoGramClient()
    try:
        res = await client.simulate_start(
            webhook_url=webhook_url,
            count=count,
            duration_seconds=duration_seconds
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await client.close()


@app.get("/api/simulate/{run_id}/truth")
async def simulate_truth_endpoint(run_id: str):
    """Proxy helper to fetch ground truth for a simulation run."""
    client = PseudoGramClient()
    try:
        return await client.simulate_truth(run_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await client.close()


# Mount static directory for frontend UI
static_path = Path(__file__).parent / "static"
static_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


@app.get("/")
async def root():
    """Serves the interactive dashboard."""
    index_file = static_path / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "LinkPlease API is running. Visit /stats for live metrics."}
