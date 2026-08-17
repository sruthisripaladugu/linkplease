import time
import pytest
import asyncio
from app.rate_limiter import SlidingWindowRateLimiter


@pytest.mark.asyncio
async def test_sliding_window_rate_limiter_capacity():
    # Test rate limiter with 3 requests per 1 second window
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=1.0)

    # First 3 should acquire immediately
    start = time.time()
    await limiter.acquire()
    await limiter.acquire()
    await limiter.acquire()
    elapsed = time.time() - start
    assert elapsed < 0.2

    # 4th request must wait until the window rolls over (~1s)
    await limiter.acquire()
    elapsed_total = time.time() - start
    assert elapsed_total >= 0.95


@pytest.mark.asyncio
async def test_rate_limiter_dynamic_pause():
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60.0)

    # Pause for 0.5 seconds (e.g. from 429 Retry-After)
    await limiter.pause_for(0.5)
    start = time.time()
    await limiter.acquire()
    elapsed = time.time() - start
    assert elapsed >= 0.45
