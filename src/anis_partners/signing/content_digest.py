"""RFC 9530 digest rendering for the exact body bytes sent."""

import base64
import hashlib


class ContentDigest:
    """Build the body digest so Anis can detect a body changed after it was signed."""

    @staticmethod
    def of(body: bytes) -> str:
        """Hash the exact bytes sent; hashing a re-serialized body makes Anis reject the request."""
        digest = base64.b64encode(hashlib.sha256(body).digest()).decode("ascii")
        return f"sha-256=:{digest}:"
