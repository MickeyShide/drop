import secrets


def generate_public_id() -> str:
    return secrets.token_urlsafe(12)
