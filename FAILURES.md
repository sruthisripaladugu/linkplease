# FAILURES.md — System Edge Cases, Failure Modes & Tradeoffs

This document provides a candid, engineering-level breakdown of how the LinkPlease automation engine can experience failures, duplicate transmissions, or metric discrepancies under specific boundary conditions.

---

### 1. In-Flight Process Termination During Network Transmission
* **Failure Condition:** The outbox worker pops a job from SQLite, transitions its state to `sending`, acquires a rate-limit token, and initiates an HTTP POST request to `/v1/dm/send`. If the host OS terminates the process (SIGKILL, container OOM, or spot instance eviction) while the HTTP socket is in transit:
  * The mock API may have successfully received and processed the request (creating a DM), but our server never receives the response.
  * When the service restarts, SQLite still marks this job in `sending` state.
  * **Consequence:** Without an automated recovery sweep on boot that re-checks in-flight jobs via `Idempotency-Key` or marks orphaned `sending` jobs back to `queued_send`, the DM is either stuck in `sending` indefinitely or sent a second time upon reboot if not reconciled against the upstream API.

---

### 2. Upstream Clock Skew vs. Sliding Window Burst Boundary
* **Failure Condition:** Our sliding window rate limiter tracks outgoing requests within a rolling 60-second window in memory using monotonic and wall-clock timestamps. 
  * If the client system's system clock drifts or if the remote server calculates the 60-second rolling window with slight boundary differences (e.g. fixed 60s windows rather than sliding window), 10 requests fired in seconds 50-59 followed immediately by 10 requests at second 61 could trigger a `429 Too Many Requests` response from the upstream API.
  * **Mitigation / Handling:** While our rate limiter includes safety margins (0.05s buffer) and dynamically pauses when a `429` with `Retry-After` header is returned, receiving a 429 delays the queue drain rate by the duration of the cooldown.

---

### 3. Asymmetric Reconciliation Polling Lag on Massive Spikes
* **Failure Condition:** When 500 comment events arrive within a 10-second burst, all 500 are immediately validated, deduplicated, and inserted into SQLite within milliseconds (<5ms per webhook). However, the upstream API limits outgoing `POST /v1/dm/send` to 10 requests per 60 seconds (1 DM every ~6 seconds).
  * Consequently, sending all 500 accepted DMs requires **at least 50 minutes** of sustained rate-limited queue draining.
  * Because the mock API marks ~15% of accepted DMs as `failed` asynchronously, our reconciliation poller (`GET /v1/dm/{dm_id}`) checks status in batches.
  * During this 50-minute drain window, `GET /stats` will report a high `queued` count (e.g., 480) and low `sent` count (e.g., 20). If an external observer expects `/stats` to reflect final delivered counts immediately after the 10-second simulation completes, they will see intermediate state until the outbox worker completes its rate-limited queue drain.

---

### 4. Delayed `comment.deleted` Arriving After Mock API Acceptance
* **Failure Condition:** If a creator or commenter deletes their comment:
  * **Scenario A (Arrives while queued in local SQLite):** Our webhook handler updates the job status to `cancelled`. The DM is never sent.
  * **Scenario B (Arrives after `POST /v1/dm/send` returned 202 Accepted):** The message has already entered the platform's delivery pipeline. Because platform APIs (and the mock API) do not offer a `DELETE /v1/dm/{dm_id}` cancellation endpoint once accepted, the DM will still be delivered to the recipient despite the comment having been deleted.

---

### 5. Multi-Instance Concurrency Race on User Deduplication (Distributed Scaling)
* **Failure Condition:** In our current architecture, SQLite is configured with Write-Ahead Logging (WAL) and atomic `INSERT INTO user_rule_deliveries (user_id, rule_id)` with a composite primary key. On a single instance or worker process, this guarantees strict zero-duplicate delivery.
  * If the service is scaled horizontally across multiple distinct physical servers without a centralized database (e.g., separate SQLite files on different container nodes behind a round-robin load balancer), two webhook requests for the same `(user_id, rule_id)` hitting different instances at the same millisecond could both pass local deduplication and send duplicate DMs.
  * **Production Requirement:** For multi-node deployments, a centralized database (PostgreSQL with `UNIQUE(user_id, rule_id)` and row-level locking or Redis distributed locks) is required.
