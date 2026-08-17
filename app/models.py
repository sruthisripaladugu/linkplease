from typing import Optional, Any
from pydantic import BaseModel, Field, ConfigDict


# --- Rules API Models ---
class CreateRuleRequest(BaseModel):
    keyword: str
    dm_message: str


class RuleResponse(BaseModel):
    rule_id: str
    keyword: str
    dm_message: str


# --- Webhook Models ---
class WebhookUserData(BaseModel):
    user_id: str
    username: Optional[str] = None


class WebhookData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    comment_id: str
    post_id: Optional[str] = None
    text: Optional[str] = None
    created_at: Optional[str] = None
    from_: Optional[WebhookUserData] = Field(default=None, alias="from")


class WebhookEvent(BaseModel):
    event_id: str
    event_type: str
    sent_at: Optional[str] = None
    data: WebhookData


# --- Stats Models ---
class StatsResponse(BaseModel):
    sent: int
    failed: int
    queued: int
    duplicates_blocked: int


# --- Mock API Request/Response Models ---
class MockSendDMRequest(BaseModel):
    recipient_user_id: str
    message: str
    comment_id: str


class MockSendDMResponse(BaseModel):
    dm_id: str
    status: str  # e.g., 'queued'


class MockDMStatusResponse(BaseModel):
    dm_id: str
    status: str  # 'queued', 'delivered', 'failed'
    recipient_user_id: Optional[str] = None
    updated_at: Optional[str] = None


# --- Internal DM Job Model ---
class DMJob(BaseModel):
    id: int
    job_id: str
    user_id: str
    rule_id: str
    comment_id: str
    message: str
    status: str  # 'queued_send', 'sending', 'waiting_reconciliation', 'sent', 'failed', 'cancelled'
    dm_id: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 5
    next_run_at: float
    idempotency_key: str
    last_error: Optional[str] = None
    created_at: float
    updated_at: float
