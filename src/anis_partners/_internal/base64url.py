"""Strict base64url helpers matching the wire contract."""

import base64
import binascii


def encode(value: bytes) -> str:
    """Encode bytes as unpadded RFC 4648 base64url."""
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def decode(value: str | None) -> bytes | None:
    """Decode unpadded base64url, returning None for padding, invalid characters, or impossible lengths."""
    if (
        not value
        or len(value) % 4 == 1
        or any(not (char.isascii() and char.isalnum()) and char not in "-_" for char in value)
    ):
        return None
    try:
        decoded = base64.b64decode(value.replace("-", "+").replace("_", "/") + "=" * (-len(value) % 4), validate=True)
        return decoded if encode(decoded) == value else None
    except (binascii.Error, ValueError):
        return None
