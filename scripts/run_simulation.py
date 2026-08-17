"""
Simulation runner and truth validator script.
"""
import sys
import time
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY", "")
BASE_URL = os.getenv("PSEUDOGRAM_API_BASE_URL", "https://pseudogram-api.onrender.com")


def run_simulation(webhook_url: str, count: int = 500, duration: int = 10):
    if not API_KEY:
        print("Warning: API_KEY not set in environment or .env file.")

    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    client = httpx.Client(base_url=BASE_URL, headers=headers, timeout=30.0)

    print(f"Triggering simulation: {count} events over {duration}s -> {webhook_url}")
    payload = {
        "webhook_url": webhook_url,
        "count": count,
        "duration_seconds": duration
    }

    res = client.post("/v1/simulate/start", json=payload)
    if res.status_code != 200:
        print(f"Error starting simulation: {res.status_code} - {res.text}")
        sys.exit(1)

    data = res.json()
    run_id = data.get("run_id")
    print(f"✓ Simulation started! Run ID: {run_id}")

    print("\nWaiting for simulation events and rate-limited processing to finish...")
    print(f"You can check truth with: GET {BASE_URL}/v1/simulate/{run_id}/truth")
    return run_id


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.run_simulation <webhook_url> [count] [duration]")
        sys.exit(1)

    target_url = sys.argv[1]
    cnt = int(sys.argv[2]) if len(sys.argv) > 2 else 500
    dur = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    run_simulation(target_url, cnt, dur)
