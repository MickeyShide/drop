import os


def sanitize_filename(filename: str | None) -> str:
    if not filename:
        return "file"

    # Remove path directory separators (prevent path traversal)
    clean = os.path.basename(filename.replace("\\", "/"))

    # Remove control characters and null bytes
    clean = "".join(char for char in clean if ord(char) >= 32 and ord(char) != 127)

    # Remove leading dots or slashes
    clean = clean.lstrip(". /\\")

    # Truncate to maximum 255 characters
    clean = clean[:255].strip()

    return clean or "file"


def sanitize_content_type(content_type: str | None) -> str:
    if not content_type:
        return "application/octet-stream"

    clean = content_type.strip().lower()

    if not clean or "/" not in clean:
        return "application/octet-stream"

    return clean
