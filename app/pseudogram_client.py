import httpx
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any
from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SendDMResult:
    success: bool
    status_code: int
    dm_id: Optional[str] = None
    status: Optional[str] = None
    retry_after: Optional[float] = None
    error_type: Optional[str] = None
    error_detail: Optional[str] = None


@dataclass
class DMStatusResult:
    success: bool
    status_code: int
    dm_id: Optional[str] = None
    status: Optional[str] = None  # 'queued', 'delivered', 'failed'
    error_detail: Optional[str] = None


class PseudoGramClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, timeout: float = 15.0):
        self.base_url = (base_url or settings.PSEUDOGRAM_API_BASE_URL).rstrip("/")
        self.api_key = api_key or settings.API_KEY
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {}
            if self.api_key:
                headers["X-API-Key"] = self.api_key
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def send_dm(
        self,
        recipient_user_id: str,
        message: str,
        comment_id: str,
        idempotency_key: Optional[str] = None
    ) -> SendDMResult:
        client = await self.get_client()
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        payload = {
            "recipient_user_id": recipient_user_id,
            "message": message,
            "comment_id": comment_id
        }

        try:
            response = await client.post("/v1/dm/send", json=payload, headers=headers)
            
            if response.status_code == 202:
                data = response.json()
                return SendDMResult(
                    success=True,
                    status_code=202,
                    dm_id=data.get("dm_id"),
                    status=data.get("status", "queued")
                )
            
            elif response.status_code == 429:
                retry_after_str = response.headers.get("Retry-After")
                retry_after = float(retry_after_str) if retry_after_str else 5.0
                return SendDMResult(
                    success=False,
                    status_code=429,
                    retry_after=retry_after,
                    error_type="rate_limited",
                    error_detail=response.text
                )
            
            elif response.status_code == 500:
                return SendDMResult(
                    success=False,
                    status_code=500,
                    error_type="internal_error",
                    error_detail=response.text
                )
            
            elif response.status_code == 400:
                return SendDMResult(
                    success=False,
                    status_code=400,
                    error_type="invalid_request",
                    error_detail=response.text
                )
            
            else:
                return SendDMResult(
                    success=False,
                    status_code=response.status_code,
                    error_type=f"http_{response.status_code}",
                    error_detail=response.text
                )

        except httpx.RequestError as e:
            logger.error(f"HTTP request error when sending DM: {e}")
            return SendDMResult(
                success=False,
                status_code=0,
                error_type="network_error",
                error_detail=str(e)
            )

    async def get_dm_status(self, dm_id: str) -> DMStatusResult:
        client = await self.get_client()
        try:
            response = await client.get(f"/v1/dm/{dm_id}")
            if response.status_code == 200:
                data = response.json()
                return DMStatusResult(
                    success=True,
                    status_code=200,
                    dm_id=data.get("dm_id"),
                    status=data.get("status")
                )
            else:
                return DMStatusResult(
                    success=False,
                    status_code=response.status_code,
                    error_detail=response.text
                )
        except httpx.RequestError as e:
            logger.error(f"HTTP request error checking DM status {dm_id}: {e}")
            return DMStatusResult(
                success=False,
                status_code=0,
                error_detail=str(e)
            )

    async def apply(self, data: Dict[str, Any]) -> Dict[str, Any]:
        client = await self.get_client()
        response = await client.post("/v1/apply", json=data)
        response.raise_for_status()
        return response.json()

    async def keygen(self, email: str) -> Dict[str, Any]:
        client = await self.get_client()
        response = await client.post("/v1/keygen", json={"email": email})
        response.raise_for_status()
        return response.json()

    async def simulate_start(self, webhook_url: str, count: int = 500, duration_seconds: int = 10) -> Dict[str, Any]:
        client = await self.get_client()
        payload = {
            "webhook_url": webhook_url,
            "count": count,
            "duration_seconds": duration_seconds
        }
        response = await client.post("/v1/simulate/start", json=payload)
        response.raise_for_status()
        return response.json()

    async def simulate_truth(self, run_id: str) -> Dict[str, Any]:
        client = await self.get_client()
        response = await client.get(f"/v1/simulate/{run_id}/truth")
        response.raise_for_status()
        return response.json()
