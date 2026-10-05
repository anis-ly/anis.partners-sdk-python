"""Fingerprint submitted public keys so enrollment detects key substitution before proof is trusted."""

import hashlib
import hmac
import json

from anis_partners._internal.base64url import decode, encode
from anis_partners.verification.partner_jwk import PartnerJwk


def compute(public_jwk: PartnerJwk) -> str:
    """Compute the RFC 7638 fingerprint locally so a changed or substituted submitted key is detected."""
    if public_jwk.kty != "EC" or public_jwk.crv != "P-256":
        raise ValueError("The key must be an EC P-256 public JWK.")
    x = decode(public_jwk.x)
    y = decode(public_jwk.y)
    if x is None or y is None or len(x) != 32 or len(y) != 32:
        raise ValueError("JWK x and y must each decode to a 32-byte P-256 coordinate.")
    canonical = json.dumps(
        {"crv": "P-256", "kty": "EC", "x": public_jwk.x, "y": public_jwk.y},
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return encode(hashlib.sha256(canonical.encode("utf-8")).digest())


def fixed_time_equals(left: str, right: str) -> bool:
    """Compare in fixed time so fingerprint differences do not leak through comparison timing."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
