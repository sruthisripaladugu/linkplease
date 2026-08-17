# LinkPlease — Instagram DM Automation Engine

A high-performance, fault-tolerant Instagram DM automation service built to withstand hostile platform API conditions (rate limits, 500 errors, delayed delivery failures, webhook replays, out-of-order deliveries, and comment deletions).

Built for the **LinkPlease Tech Intern Assignment**, implementing **Part A, Part B, and Part C**.

---

## Features & Scope Completed

### Part A (Core Automation & Deduplication) — Complete
- **Rule Engine (`POST /rules`)**: Dynamic keyword trigger configuration matching case-insensitively across comment text.
- **Fast Webhook Intake (`POST /webhook`)**: Immediate `<5ms` response time to prevent webhook timeouts.
- **Strict Deduplication**: Guaranteed single DM per `(user_id, rule_id)` combination, regardless of comment spam.
- **Zero Silent Losses**: Persistent transactional SQLite outbox with exponential backoff retries.

### Part B (Security & Live Metrics) — Complete
- **HMAC-SHA256 Webhook Verification**: Validates raw body signatures via `X-PseudoGram-Signature` using constant-time comparison (`hmac.compare_digest`).
- **Live Accurate Stats (`GET /stats`)**: Real-time counts for `sent`, `failed`, `queued`, and `duplicates_blocked` under concurrent load.

### Part C (Hostile Edge Cases & Rate Limiting) — Complete
- **Delivery Reconciliation (`GET /v1/dm/{dm_id}`)**: Unthrottled periodic polling catches the ~15% of `202 Accepted` DMs that later transition to `failed`, automatically re-enqueuing them.
- **`comment.deleted` Handling**: Automatically cancels pending DMs before they leave the outbox.
- **Sliding Window Rate Limiter**: Strictly enforces the upstream limit of **≤ 10 requests per rolling 60 seconds** on `POST /v1/dm/send`. Even under bursts of 500 comments in 10 seconds, zero DMs are dropped and the rate limit is never breached.
- **Interactive UI Dashboard**: Sleek, modern control center with real-time stats, rule management, simulation runner, and live activity log.

---

## API Contract

### 1. `POST /rules`
Creates an automated DM keyword rule.
- **Status:** `201 Created`
- **Request:**
  ```json
  {
    "keyword": "PRICE",
    "dm_message": "Hey! Here is the price list: https://example.com/pricing"
  }
  ```
- **Response:**
  ```json
  {
    "rule_id": "rule_8f3a12",
    "keyword": "PRICE",
    "dm_message": "Hey! Here is the price list: https://example.com/pricing"
  }
  ```

### 2. `POST /webhook`
Receives comment events from Instagram / Pseudogram.
- **Status:** `200 OK` (Responds within <5ms)
- **Header:** `X-PseudoGram-Signature: sha256=<hex>`
- **Payload:**
  ```json
  {
    "event_id": "evt_01J8ZQ4K2N7RXA",
    "event_type": "comment.created",
    "sent_at": "2026-08-10T09:14:22.481Z",
    "data": {
      "comment_id": "cmt_9f2a7c",
      "post_id": "post_44de1b",
      "text": "PRICE please 🙏",
      "created_at": "2026-08-10T09:14:21.900Z",
      "from": {
        "user_id": "usr_3b91fe",
        "username": "arjun.shoots"
      }
    }
  }
  ```

### 3. `GET /stats`
Reports live operational metrics.
- **Response:**
  ```json
  {
    "sent": 142,
    "failed": 3,
    "queued": 8,
    "duplicates_blocked": 57
  }
  ```

---

## Architecture Diagram

```
                 [ Mock API / Webhooks ]
                            │
                            ▼ (POST /webhook + HMAC)
             ┌─────────────────────────────┐
             │   FastAPI Webhook Handler   │ ◄─── Responds 200 OK in <5ms
             └──────────────┬──────────────┘
                            │ (Deduplicate event_id & user_id)
                            ▼
             ┌─────────────────────────────┐
             │ SQLite Outbox (WAL Mode)    │
             └──────────────┬──────────────┘
                            │
             ┌──────────────┴──────────────┐
             ▼                             ▼
┌──────────────────────────┐  ┌──────────────────────────┐
│   Outbox Worker Loop     │  │  Reconciliation Poller   │
│  (Sliding Window Limiter │  │  (Unthrottled GET status) │
│    ≤ 10 req / 60 sec)    │  │  Catches ~15% late fails  │
└────────────┬─────────────┘  └────────────┬─────────────┘
             ▼                             ▼
       [ POST /v1/dm/send ]          [ GET /v1/dm/{id} ]
```

---

## Quick Start & Local Setup

### 1. Prerequisites
- Python 3.11+ or `uv` (recommended)

### 2. Installation
```bash
# Clone repository
git clone <your-repo-url>
cd linkplease

# Install dependencies using uv
uv sync

# Or with pip
pip install -r requirements.txt
```

### 3. Obtain API Key & Configuration
Run the automated helper to register and fetch your key from Pseudogram:
```bash
uv run python -m scripts.apply_and_keygen
```
Or copy `.env.example` to `.env` and fill in `API_KEY`:
```bash
cp .env.example .env
```

### 4. Run the Service
```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Open your browser at `http://localhost:8000` to view the interactive dashboard.

---

## Running Automated Tests

Run the complete test suite covering HMAC verification, deduplication, rate limiting, and edge cases:
```bash
uv run pytest -v
```

---

## Running Simulation & Truth Verification

Trigger a 500-event burst test against your deployed or local service:
```bash
uv run python -m scripts.run_simulation https://your-domain.com/webhook 500 10
```
Then inspect ground truth comparison at:
```
GET https://pseudogram-api.onrender.com/v1/simulate/{run_id}/truth
```

---

## Deployment Guide

### Deploying to Render
1. Push this repository to GitHub.
2. Create a new **Web Service** on [Render](https://render.com).
3. Connect your GitHub repository (or use the included `render.yaml` Blueprint).
4. Set Environment Variables:
   - `API_KEY`: Your Pseudogram API key.
   - `PSEUDOGRAM_API_BASE_URL`: `https://pseudogram-api.onrender.com`
5. Build Command: `pip install -r requirements.txt`
6. Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

---

## Project Structure

```
├── app/
│   ├── config.py              # Configuration & settings management
│   ├── db.py                  # SQLite WAL database & queries
│   ├── models.py              # Pydantic schemas & data models
│   ├── security.py            # HMAC-SHA256 signature verification
│   ├── rate_limiter.py        # Sliding-window rate limiter
│   ├── pseudogram_client.py   # Async client for mock API
│   ├── worker.py              # Outbox & reconciliation background workers
│   ├── main.py                # FastAPI routing & lifecycle
│   └── static/                # Interactive web dashboard
│       ├── index.html
│       ├── style.css
│       └── app.js
├── tests/                     # 100% passing test suite
│   ├── test_rules.py
│   ├── test_webhook.py
│   ├── test_dedup.py
│   ├── test_comment_deleted.py
│   ├── test_rate_limiter.py
│   ├── test_reconciliation.py
│   └── test_stats.py
├── scripts/
│   ├── apply_and_keygen.py    # Applicant registration & key generator
│   ├── run_simulation.py      # Simulation runner
│   └── submit.py              # Final assignment submission tool
├── FAILURES.md                # Detailed analysis of edge cases & failure modes
├── LOOM_SCRIPT.md             # 3-minute video presentation guide
├── Dockerfile                 # Container packaging
├── render.yaml                # Infrastructure configuration
├── Procfile                   # Process definition
└── requirements.txt           # Python dependencies
```
