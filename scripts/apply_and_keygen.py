"""
Helper script to apply for the LinkPlease Tech Intern mock API and generate your API key.
Saves the resulting API key to .env automatically.
"""
import sys
import httpx

BASE_URL = "https://pseudogram-api.onrender.com"


def apply_and_keygen():
    print("=== Pseudogram Mock API Key Setup ===")
    name = input("Enter your full name: ").strip()
    email = input("Enter your email: ").strip()
    phone = input("Enter your phone number (e.g. +91...): ").strip()
    whatsapp = input("Enter whatsapp (press enter if same as phone): ").strip() or phone
    linkedin_url = input("Enter your LinkedIn profile URL: ").strip()

    if not all([name, email, phone, linkedin_url]):
        print("Error: Name, email, phone, and LinkedIn URL are required!")
        sys.exit(1)

    client = httpx.Client(base_url=BASE_URL, timeout=30.0)

    # Step 1: Apply
    print(f"\n1. Submitting application to {BASE_URL}/v1/apply ...")
    apply_payload = {
        "name": name,
        "email": email,
        "phone": phone,
        "whatsapp": whatsapp,
        "linkedin_url": linkedin_url
    }
    try:
        apply_res = client.post("/v1/apply", json=apply_payload)
        if apply_res.status_code not in (200, 201):
            print(f"Application failed: {apply_res.status_code} - {apply_res.text}")
            sys.exit(1)
        print("✓ Application submitted successfully!")
    except Exception as e:
        print(f"Error connecting to API: {e}")
        sys.exit(1)

    # Step 2: Keygen
    print(f"\n2. Requesting API key for {email} from {BASE_URL}/v1/keygen ...")
    try:
        keygen_res = client.post("/v1/keygen", json={"email": email})
        if keygen_res.status_code != 200:
            print(f"Keygen failed: {keygen_res.status_code} - {keygen_res.text}")
            sys.exit(1)

        key_data = keygen_res.json()
        api_key = key_data.get("api_key")
        print(f"✓ Obtained API Key: {api_key}")

        # Write to .env
        env_content = f"""# LinkPlease Configuration
API_KEY={api_key}
PSEUDOGRAM_API_BASE_URL=https://pseudogram-api.onrender.com
DATABASE_PATH=linkplease.db
RATE_LIMIT_MAX_REQUESTS=10
RATE_LIMIT_WINDOW_SECONDS=60.0
MAX_RETRIES=5
"""
        with open(".env", "w") as f:
            f.write(env_content)
        print("✓ Saved configuration to .env file!")

    except Exception as e:
        print(f"Error obtaining API key: {e}")
        sys.exit(1)


if __name__ == "__main__":
    apply_and_keygen()
