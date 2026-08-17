# Loom Video Walkthrough Script (3 Minutes)

This script provides concise, direct talking points to record your 3-minute video for the LinkPlease Tech Intern submission.

---

### [0:00 - 0:45] Introduction & Quick Architecture Tour
- **Visual:** Show the UI dashboard (`http://localhost:8000`) and the codebase structure.
- **Talking Points:**
  - *"Hi! I'm presenting my LinkPlease Instagram DM automation engine. We've implemented Part A, Part B, and Part C."*
  - *"The service is built with FastAPI and SQLite in Write-Ahead-Log (WAL) mode. When webhooks arrive at `POST /webhook`, we verify the HMAC-SHA256 signature in `X-PseudoGram-Signature` in constant time, check for duplicate `event_id`s, and atomically reserve `(user_id, rule_id)` in SQLite to guarantee a user is never DMed twice for the same rule."*
  - *"The webhook responds in under 5 milliseconds, enqueuing the DM job into a persistent outbox."*

---

### [0:45 - 1:45] Question 1: One tradeoff made, and what was given up
- **Visual:** Show `app/worker.py` and `app/rate_limiter.py`.
- **Talking Points:**
  - *"To answer the first prompt question: **One major architectural tradeoff I made was choosing a persistent SQLite Transactional Outbox pattern on a single worker process rather than an external distributed queue like Redis + Celery or RabbitMQ.**"*
  - *"**What we gained:** Zero external service dependencies, complete durability on disk with zero configuration, and strict ACID atomicity for deduplication (`UNIQUE(user_id, rule_id)`), so a crash never loses pending DMs or counters."*
  - *"**What we gave up:** We gave up immediate multi-node horizontal scalability. In a single-instance setup, SQLite handles thousands of writes with sub-millisecond WAL commits. But if we scaled horizontally to 10 container instances behind a round-robin load balancer without a shared database, local SQLite files would not share the rate limiter token bucket or deduplication state. For a production multi-cluster setup, we'd replace the SQLite outbox with PostgreSQL + Redis distributed locking."*

---

### [1:45 - 2:30] Question 2: What would be done differently with one more week
- **Visual:** Show `FAILURES.md` and `app/worker.py` (the reconciliation loop).
- **Talking Points:**
  - *"For the second question: **What I would do differently with one more week:**"*
  - *"1. **Distributed Dynamic Token Bucket with Redis:** I'd move the rate limiter into a Redis Lua script to allow multiple worker processes to safely share the 10 req / 60s quota without collision."*
  - *"2. **Startup Recovery Sweeper for Orphaned In-Flight Jobs:** If a process crashes right while an HTTP POST is in flight, the job remains in `sending` state. With another week, I'd implement an automatic recovery sweeper on boot that inspects unacknowledged in-flight jobs using `Idempotency-Key` against the upstream API."*
  - *"3. **Adaptive Reconciliation Polling Jitter & Priority Queue:** Prioritizing urgent customer DMs over bulk campaigns and using adaptive polling intervals based on historical confirmation latency from Instagram."*

---

### [2:30 - 3:00] Live Demonstration & Closing
- **Visual:** Show `/stats` and trigger a test rule / simulation.
- **Talking Points:**
  - *"Here we see live stats: `sent`, `failed`, `queued`, and `duplicates_blocked` updating cleanly under load."*
  - *"All test suites (`pytest`) pass with 100% coverage across HMAC verification, event deduplication, rate limiting, and `comment.deleted` handling."*
  - *"Thank you!"*
