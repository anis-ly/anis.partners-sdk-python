"""Provide a short key fingerprint staff and partners can compare during out-of-band enrollment approval."""

import hmac

from anis_partners._internal.base64url import decode


class SafetyCode:
    """Make key confirmation practical by phone so approval is tied to the partner's intended key."""

    ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

    @classmethod
    def from_thumbprint(cls, thumbprint: str) -> str:
        """Encode 80 thumbprint bits for a manageable phone check while detecting a mismatched key."""
        digest = decode(thumbprint)
        if digest is None or len(digest) != 32:
            raise ValueError("A thumbprint must be unpadded base64url encoding of 32 bytes.")
        bits = int.from_bytes(digest[:10], "big")
        code = "".join(cls.ALPHABET[(bits >> shift) & 31] for shift in range(75, -1, -5))
        return "-".join(code[index : index + 4] for index in range(0, 16, 4))

    @classmethod
    def matches(cls, entered: str | None, thumbprint: str) -> bool:
        """Accept common Crockford aliases during phone read-back so formatting does not cause a false mismatch."""
        raw = (entered or "").strip()
        normalized = raw.replace(" ", "").replace("-", "").upper().replace("O", "0").replace("I", "1").replace("L", "1")
        if len(normalized) == 16:
            expected = cls.from_thumbprint(thumbprint).replace("-", "")
            return hmac.compare_digest(normalized.encode(), expected.encode())
        return hmac.compare_digest(raw.encode(), thumbprint.encode())
