import hashlib
import hmac
import secrets


def generate_access_token() -> str:
    """Generate a 256-bit URL-safe capability access token."""
    return secrets.token_urlsafe(32)


def compute_token_hash(token: str, pepper: str) -> bytes:
    """Compute HMAC-SHA256 digest for an access token using a server-side pepper."""
    return hmac.new(
        key=pepper.encode("utf-8"),
        msg=token.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()


def verify_access_token(provided_token: str, stored_hash: bytes, pepper: str) -> bool:
    """Constant-time verification of capability access token against stored HMAC hash."""
    computed = compute_token_hash(provided_token, pepper)
    return secrets.compare_digest(computed, stored_hash)


def generate_session_id() -> str:
    """Generate a 256-bit random anonymous client session ID."""
    return secrets.token_urlsafe(32)


def compute_session_hash(session_id: str, pepper: str) -> bytes:
    """Compute HMAC-SHA256 digest for a client session ID."""
    return hmac.new(
        key=pepper.encode("utf-8"),
        msg=session_id.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()


def pseudonymize_ip(ip_address: str, pepper: str) -> str:
    """Compute keyed HMAC-SHA256 pseudonym for client IP address for privacy-preserving logs."""
    return hmac.new(
        key=pepper.encode("utf-8"),
        msg=ip_address.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()[:32]
