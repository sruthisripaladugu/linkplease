import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PSEUDOGRAM_API_BASE_URL: str = os.getenv("PSEUDOGRAM_API_BASE_URL", "https://pseudogram-api.onrender.com")
    API_KEY: str = os.getenv("API_KEY", os.getenv("PSEUDOGRAM_API_KEY", ""))
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "linkplease.db")
    
    # Rate limit: 10 requests per 60 seconds rolling window for POST /v1/dm/send
    RATE_LIMIT_MAX_REQUESTS: int = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "10"))
    RATE_LIMIT_WINDOW_SECONDS: float = float(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60.0"))
    
    # Retry configuration
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "5"))
    BASE_RETRY_DELAY_SECONDS: float = float(os.getenv("BASE_RETRY_DELAY_SECONDS", "2.0"))
    
    # Worker intervals
    WORKER_POLL_INTERVAL_SECONDS: float = float(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "0.25"))
    RECONCILIATION_INTERVAL_SECONDS: float = float(os.getenv("RECONCILIATION_INTERVAL_SECONDS", "2.0"))
    RECONCILIATION_MAX_POLL_ATTEMPTS: int = int(os.getenv("RECONCILIATION_MAX_POLL_ATTEMPTS", "10"))
    
    # Webhook signature enforcement (if True, reject invalid signature; if API_KEY is set, always verified)
    ENFORCE_WEBHOOK_SIGNATURE: bool = os.getenv("ENFORCE_WEBHOOK_SIGNATURE", "false").lower() in ("true", "1", "yes")


settings = Settings()
