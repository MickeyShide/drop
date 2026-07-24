import secrets


def generate_public_id() -> str:
    # The public ID is only a locator, but 128 bits also make accidental
    # enumeration impractical before capability verification is attempted.
    return secrets.token_urlsafe(16)
