import asyncio
import time
import logging
from collections import deque
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)


class SlidingWindowRateLimiter:
    """
    Sliding window rate limiter enforcing at most `max_requests` per `window_seconds`.
    Also respects dynamic server backoffs (429 Retry-After).
    """
    def __init__(self, max_requests: int = 10, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.timestamps = deque()
        self.paused_until: float = 0.0
        self._lock = asyncio.Lock()

    async def pause_for(self, seconds: float) -> None:
        """Pause all outbound requests for a specific duration (e.g. from Retry-After header)."""
        async with self._lock:
            self.paused_until = max(self.paused_until, time.time() + seconds)
            logger.warning(f"RateLimiter paused for {seconds:.2f}s (until {self.paused_until:.2f})")

    async def get_wait_time(self) -> float:
        """Returns how many seconds to wait before a token is available, or 0.0 if ready immediately."""
        async with self._lock:
            now = time.time()
            # 1. Check dynamic pause (e.g. from 429)
            if now < self.paused_until:
                return self.paused_until - now

            # 2. Prune old timestamps outside the window
            cutoff = now - self.window_seconds
            while self.timestamps and self.timestamps[0] <= cutoff:
                self.timestamps.popleft()

            # 3. Check capacity
            if len(self.timestamps) < self.max_requests:
                return 0.0

            # 4. Wait until the oldest token in the window expires (+ small safety margin)
            oldest = self.timestamps[0]
            wait_needed = (oldest + self.window_seconds) - now + 0.05
            return max(0.0, wait_needed)

    async def acquire(self) -> None:
        """
        Blocks asynchronously until a rate limit slot is available, then records the timestamp.
        """
        while True:
            wait_time = await self.get_wait_time()
            if wait_time <= 0.0:
                async with self._lock:
                    now = time.time()
                    # Double-check inside lock
                    if now < self.paused_until:
                        continue
                    cutoff = now - self.window_seconds
                    while self.timestamps and self.timestamps[0] <= cutoff:
                        self.timestamps.popleft()

                    if len(self.timestamps) < self.max_requests:
                        self.timestamps.append(now)
                        return
            else:
                logger.info(f"RateLimiter: waiting {wait_time:.2f}s for slot ({len(self.timestamps)}/{self.max_requests} in window)")
                await asyncio.sleep(wait_time)


# Global rate limiter instance initialized with settings
outbound_rate_limiter = SlidingWindowRateLimiter(
    max_requests=settings.RATE_LIMIT_MAX_REQUESTS,
    window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS
)
