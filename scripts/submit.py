"""
Submission helper script for LinkPlease Tech Intern Assignment.
"""
import sys
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

SUBMIT_URL = "https://pseudogram-api.onrender.com/v1/submit"


def submit_assignment():
    print("=== LinkPlease Assignment Submission ===")
    email = input("Enter email (used during application): ").strip()
    github_repo = input("Enter GitHub repository URL (public): ").strip()
    working_url = input("Enter working deployed URL (e.g., https://your-app.onrender.com): ").strip()
    loom_url = input("Enter Loom video URL (3 mins): ").strip()
    parts_completed = input("Enter parts completed (A, A+B, or A+B+C) [default: A+B+C]: ").strip() or "A+B+C"
    start_date = input("Enter start date (YYYY-MM-DD) [e.g. 2026-08-25]: ").strip()

    if not all([email, github_repo, working_url, loom_url, start_date]):
        print("Error: All fields are required!")
        sys.exit(1)

    payload = {
        "email": email,
        "github_repo": github_repo,
        "working_url": working_url.rstrip("/"),
        "loom_url": loom_url,
        "parts_completed": parts_completed,
        "start_date": start_date
    }

    print(f"\nSubmitting payload to {SUBMIT_URL} ...")
    try:
        client = httpx.Client(timeout=30.0)
        res = client.post(SUBMIT_URL, json=payload)
        if res.status_code in (200, 201):
            print("✓ Assignment submitted successfully!")
            print(res.text)
        else:
            print(f"Submission returned status {res.status_code}: {res.text}")
    except Exception as e:
        print(f"Error submitting assignment: {e}")


if __name__ == "__main__":
    submit_assignment()
