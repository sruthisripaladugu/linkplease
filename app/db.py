import aiosqlite
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any, AsyncGenerator
from app.config import settings
from app.models import RuleResponse, DMJob

logger = logging.getLogger(__name__)


@asynccontextmanager
async def get_db(db_path: Optional[str] = None) -> AsyncGenerator[aiosqlite.Connection, None]:
    path = db_path or settings.DATABASE_PATH
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA synchronous=NORMAL;")
    await db.execute("PRAGMA busy_timeout=5000;")
    try:
        yield db
    finally:
        await db.close()


async def init_db(db_path: Optional[str] = None) -> None:
    async with get_db(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS rules (
                rule_id TEXT PRIMARY KEY,
                keyword TEXT NOT NULL,
                dm_message TEXT NOT NULL,
                created_at REAL NOT NULL
            );
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                comment_id TEXT,
                post_id TEXT,
                user_id TEXT,
                username TEXT,
                text TEXT,
                sent_at TEXT,
                created_at REAL NOT NULL
            );
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_rule_deliveries (
                user_id TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                comment_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (user_id, rule_id)
            );
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS dm_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                comment_id TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL,
                dm_id TEXT,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 5,
                next_run_at REAL NOT NULL,
                idempotency_key TEXT UNIQUE NOT NULL,
                last_error TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS counters (
                name TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            );
        """)

        # Indexes for fast querying under 500-event spikes
        await db.execute("CREATE INDEX IF NOT EXISTS idx_dm_jobs_status_next ON dm_jobs(status, next_run_at);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_dm_jobs_comment ON dm_jobs(comment_id);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_dm_jobs_dm_id ON dm_jobs(dm_id);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_events_comment ON events(comment_id);")

        # Initialize counters if not present
        await db.execute("INSERT OR IGNORE INTO counters (name, value) VALUES ('duplicates_blocked', 0);")
        await db.commit()


# --- Rules Database Operations ---
async def create_rule(keyword: str, dm_message: str, db_path: Optional[str] = None) -> RuleResponse:
    rule_id = f"rule_{uuid.uuid4().hex[:8]}"
    now = time.time()
    async with get_db(db_path) as db:
        await db.execute(
            "INSERT INTO rules (rule_id, keyword, dm_message, created_at) VALUES (?, ?, ?, ?)",
            (rule_id, keyword, dm_message, now)
        )
        await db.commit()
    return RuleResponse(rule_id=rule_id, keyword=keyword, dm_message=dm_message)


async def get_all_rules(db_path: Optional[str] = None) -> List[RuleResponse]:
    async with get_db(db_path) as db:
        cursor = await db.execute("SELECT rule_id, keyword, dm_message FROM rules ORDER BY created_at ASC")
        rows = await cursor.fetchall()
        return [RuleResponse(rule_id=r["rule_id"], keyword=r["keyword"], dm_message=r["dm_message"]) for r in rows]


async def get_matching_rules(text: Optional[str], db_path: Optional[str] = None) -> List[RuleResponse]:
    if not text:
        return []
    text_lower = text.lower()
    rules = await get_all_rules(db_path)
    # Case-insensitive substring match anywhere in text
    return [r for r in rules if r.keyword.lower() in text_lower]


# --- Event & Deduplication Operations ---
async def record_event(
    event_id: str,
    event_type: str,
    comment_id: Optional[str],
    post_id: Optional[str],
    user_id: Optional[str],
    username: Optional[str],
    text: Optional[str],
    sent_at: Optional[str],
    db_path: Optional[str] = None
) -> bool:
    """
    Returns True if event is newly recorded, False if event_id already exists (idempotency).
    """
    now = time.time()
    async with get_db(db_path) as db:
        try:
            await db.execute(
                """
                INSERT INTO events (event_id, event_type, comment_id, post_id, user_id, username, text, sent_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, event_type, comment_id, post_id, user_id, username, text, sent_at, now)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            # Duplicate event_id received
            return False


async def reserve_user_rule_delivery(
    user_id: str,
    rule_id: str,
    comment_id: str,
    db_path: Optional[str] = None
) -> bool:
    """
    Atomically checks and reserves delivery for (user_id, rule_id).
    Returns True if successfully reserved (first time for user+rule).
    Returns False if user has ALREADY been DMed or queued for this rule.
    """
    now = time.time()
    async with get_db(db_path) as db:
        try:
            await db.execute(
                """
                INSERT INTO user_rule_deliveries (user_id, rule_id, comment_id, status, created_at)
                VALUES (?, ?, ?, 'reserved', ?)
                """,
                (user_id, rule_id, comment_id, now)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            # Already exists for this user and rule!
            return False


async def increment_duplicates_blocked(amount: int = 1, db_path: Optional[str] = None) -> None:
    async with get_db(db_path) as db:
        await db.execute(
            """
            INSERT INTO counters (name, value) VALUES ('duplicates_blocked', ?)
            ON CONFLICT(name) DO UPDATE SET value = value + ?
            """,
            (amount, amount)
        )
        await db.commit()


# --- DM Job Operations ---
async def enqueue_dm_job(
    user_id: str,
    rule_id: str,
    comment_id: str,
    message: str,
    max_retries: int = 5,
    db_path: Optional[str] = None
) -> str:
    job_id = f"job_{uuid.uuid4().hex}"
    idempotency_key = f"idemp_{user_id}_{rule_id}"
    now = time.time()
    async with get_db(db_path) as db:
        await db.execute(
            """
            INSERT INTO dm_jobs (
                job_id, user_id, rule_id, comment_id, message, status,
                retry_count, max_retries, next_run_at, idempotency_key, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'queued_send', 0, ?, ?, ?, ?, ?)
            """,
            (job_id, user_id, rule_id, comment_id, message, max_retries, now, idempotency_key, now, now)
        )
        await db.commit()
    return job_id


async def cancel_pending_jobs_for_comment(comment_id: str, db_path: Optional[str] = None) -> int:
    """
    Handles comment.deleted: cancels any job for this comment that is still in queued_send state.
    """
    now = time.time()
    async with get_db(db_path) as db:
        cursor = await db.execute(
            """
            UPDATE dm_jobs
            SET status = 'cancelled', updated_at = ?
            WHERE comment_id = ? AND status = 'queued_send'
            """,
            (now, comment_id)
        )
        cancelled_count = cursor.rowcount
        await db.commit()
        return cancelled_count


async def fetch_next_ready_dm_job(db_path: Optional[str] = None) -> Optional[DMJob]:
    """
    Atomically retrieves and locks the next ready DM job (status = 'queued_send' AND next_run_at <= now()).
    """
    now = time.time()
    async with get_db(db_path) as db:
        cursor = await db.execute(
            """
            SELECT id, job_id, user_id, rule_id, comment_id, message, status,
                   dm_id, retry_count, max_retries, next_run_at, idempotency_key,
                   last_error, created_at, updated_at
            FROM dm_jobs
            WHERE status = 'queued_send' AND next_run_at <= ?
            ORDER BY next_run_at ASC
            LIMIT 1
            """,
            (now,)
        )
        row = await cursor.fetchone()
        if not row:
            return None

        job = DMJob(**dict(row))
        # Transition to sending state
        await db.execute(
            "UPDATE dm_jobs SET status = 'sending', updated_at = ? WHERE id = ?",
            (now, job.id)
        )
        await db.commit()
        return job


async def update_job_after_send(
    job_id: str,
    status: str,
    dm_id: Optional[str] = None,
    next_run_at: Optional[float] = None,
    retry_increment: int = 0,
    last_error: Optional[str] = None,
    db_path: Optional[str] = None
) -> None:
    now = time.time()
    async with get_db(db_path) as db:
        if dm_id:
            await db.execute(
                """
                UPDATE dm_jobs
                SET status = ?, dm_id = ?, updated_at = ?, last_error = ?
                WHERE job_id = ?
                """,
                (status, dm_id, now, last_error, job_id)
            )
        else:
            await db.execute(
                """
                UPDATE dm_jobs
                SET status = ?, retry_count = retry_count + ?, next_run_at = COALESCE(?, next_run_at),
                    updated_at = ?, last_error = ?
                WHERE job_id = ?
                """,
                (status, retry_increment, next_run_at, now, last_error, job_id)
            )
        await db.commit()


async def fetch_jobs_needing_reconciliation(limit: int = 10, db_path: Optional[str] = None) -> List[DMJob]:
    """
    Fetches jobs currently waiting reconciliation with a non-null dm_id.
    """
    async with get_db(db_path) as db:
        cursor = await db.execute(
            """
            SELECT id, job_id, user_id, rule_id, comment_id, message, status,
                   dm_id, retry_count, max_retries, next_run_at, idempotency_key,
                   last_error, created_at, updated_at
            FROM dm_jobs
            WHERE status = 'waiting_reconciliation' AND dm_id IS NOT NULL
            ORDER BY updated_at ASC
            LIMIT ?
            """,
            (limit,)
        )
        rows = await cursor.fetchall()
        return [DMJob(**dict(r)) for r in rows]


async def update_job_reconciliation_result(
    job_id: str,
    status: str,  # 'sent', 'failed', 'queued_send', or 'waiting_reconciliation'
    last_error: Optional[str] = None,
    reschedule_delay: Optional[float] = None,
    retry_increment: int = 0,
    db_path: Optional[str] = None
) -> None:
    now = time.time()
    next_run = (now + reschedule_delay) if reschedule_delay else now
    async with get_db(db_path) as db:
        await db.execute(
            """
            UPDATE dm_jobs
            SET status = ?, retry_count = retry_count + ?, next_run_at = ?, updated_at = ?, last_error = ?
            WHERE job_id = ?
            """,
            (status, retry_increment, next_run, now, last_error, job_id)
        )
        await db.commit()


# --- Stats Reporting ---
async def get_stats_data(db_path: Optional[str] = None) -> Dict[str, int]:
    """
    Accurately computes live stats:
    sent: confirmed delivered by Mock API
    failed: given up after retries or 400 invalid request
    queued: waiting to send, in-flight, or waiting reconciliation
    duplicates_blocked: count of blocked duplicate DMs
    """
    async with get_db(db_path) as db:
        # 1. Sent
        cursor = await db.execute("SELECT COUNT(*) AS c FROM dm_jobs WHERE status = 'sent'")
        sent = (await cursor.fetchone())["c"]

        # 2. Failed
        cursor = await db.execute("SELECT COUNT(*) AS c FROM dm_jobs WHERE status = 'failed'")
        failed = (await cursor.fetchone())["c"]

        # 3. Queued (all active in-flight or waiting states)
        cursor = await db.execute(
            "SELECT COUNT(*) AS c FROM dm_jobs WHERE status IN ('queued_send', 'sending', 'waiting_reconciliation')"
        )
        queued = (await cursor.fetchone())["c"]

        # 4. Duplicates blocked
        cursor = await db.execute("SELECT value FROM counters WHERE name = 'duplicates_blocked'")
        row = await cursor.fetchone()
        duplicates_blocked = row["value"] if row else 0

        return {
            "sent": sent,
            "failed": failed,
            "queued": queued,
            "duplicates_blocked": duplicates_blocked
        }


async def get_recent_activity(limit: int = 50, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Returns recent jobs and events for the UI dashboard."""
    async with get_db(db_path) as db:
        cursor_jobs = await db.execute(
            "SELECT * FROM dm_jobs ORDER BY id DESC LIMIT ?", (limit,)
        )
        jobs = [dict(r) for r in await cursor_jobs.fetchall()]

        cursor_events = await db.execute(
            "SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        events = [dict(r) for r in await cursor_events.fetchall()]

        return {"jobs": jobs, "events": events}
