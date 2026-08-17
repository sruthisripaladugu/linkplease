import hmac
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def verify_webhook_signature(
    raw_body: bytes,
    signature_header: Optional[str],
    secret_key: Optional[str]
) -> bool:
    """
    Verifies the HMAC-SHA256 signature from the X-PseudoGram-Signature header.
    Format: sha256=<hex_digest>
    """
    if not secret_key:
        # If no secret key is configured (e.g. initial dev/test), allow if not strictly enforced
        return True

    if not signature_header:
        logger.warning("Missing X-PseudoGram-Signature header when API_KEY is set")
        return False

    # Header can be "sha256=abcdef..." or just "abcdef..."
    expected_prefix = "sha256="
    if signature_header.startswith(expected_prefix):
        provided_signature = signature_header[len(expected_prefix):].strip()
    else:
        provided_signature = signature_header.strip()

    try:
        mac = hmac.new(
            secret_key.encode("utf-8"),
            msg=raw_body,
            digestmod=hashlib.sha256
        )
        computed_signature = mac.hexdigest()
        return hmac.compare_digest(computed_signature, provided_signature)
    except Exception as e:
        logger.error(f"Error computing HMAC signature: {e}")
        return False


def generate_webhook_signature(raw_body: bytes, secret_key: str) -> str:
    """
    Helper function to generate X-PseudoGram-Signature header for testing.
    """
    mac = hmac.new(
        secret_key.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256
    )
    return f"sha256={mac.hexdigest()}"
