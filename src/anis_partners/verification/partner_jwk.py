"""Parse rotating public keys and reject malformed material before it can authenticate a response."""

import json
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric import ec

from anis_partners._internal.base64url import decode


@dataclass(frozen=True, slots=True)
class PartnerJwk:
    """Represent one rotation version because responses around a key change may use different keys."""

    #: Identifies the supported key family so another curve cannot be imported as P-256.
    kty: str | None = None
    #: Restricts verification to the curve used by the Partner response contract.
    crv: str | None = None
    #: Carries the X coordinate; exact width is required to construct the P-256 point.
    x: str | None = None
    #: Carries the Y coordinate; exact width is required to construct the P-256 point.
    y: str | None = None
    #: Selects the published rotation version named by a response signature.
    kid: str | None = None
    #: Intended key use when the document supplies it.
    use: str | None = None
    #: Published algorithm metadata when supplied.
    alg: str | None = None
    #: Signals disclosure or a forged document; any non-empty value makes the document untrusted.
    d: str | None = None

    @classmethod
    def from_json(cls, data: object) -> "PartnerJwk":
        """Preserve private-member disclosure because a leaked key document must be rejected whole."""
        value = json.loads(data) if isinstance(data, (str, bytes)) else data
        if not isinstance(value, dict):
            raise ValueError("A JWK must be read from a JSON object.")
        members: dict[str, str | None] = {}
        for name in ("kty", "crv", "x", "y", "kid", "use", "alg", "d"):
            member = value.get(name)
            if member is not None and not isinstance(member, str):
                raise ValueError(f"The JWK member {name} must be text or null.")
            members[name] = member
        if "d" in value and members["d"] is None:
            members["d"] = ""
        return cls(**members)

    def to_json(self) -> dict[str, object]:
        """Write JWK member names exactly so the public part can be submitted during enrollment."""
        return {
            name: value
            for name in ("kty", "crv", "x", "y", "kid", "use", "alg", "d")
            if (value := getattr(self, name)) is not None
        }

    def public_key(self) -> ec.EllipticCurvePublicKey:
        """Reject wrong-width or off-curve coordinates before cryptography can verify with an invalid point."""
        if self.kty != "EC" or self.crv != "P-256":
            raise ValueError("The published key is not an EC P-256 key.")
        x = decode(self.x)
        y = decode(self.y)
        if x is None or y is None or len(x) != 32 or len(y) != 32:
            raise ValueError("A P-256 public key must have two 32-byte coordinates.")
        return ec.EllipticCurvePublicNumbers(
            int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1()
        ).public_key()


@dataclass(frozen=True, slots=True)
class SigningKeySet:
    """Retain rotation versions together so responses issued just before or after rotation remain verifiable."""

    #: Active, next, and retiring keys needed to verify responses across a rotation boundary.
    keys: tuple[PartnerJwk, ...] = ()

    @classmethod
    def from_json(cls, document: str | bytes) -> "SigningKeySet":
        """Retain private-member disclosure so a compromised or mispublished document is refused as a whole."""
        value = json.loads(document)
        if not isinstance(value, dict) or not isinstance(value.get("keys", []), list):
            raise ValueError("The signing key document must contain a keys array.")
        parsed_keys = [PartnerJwk.from_json(item) for item in value.get("keys", [])]
        return cls(tuple(parsed_keys))


PartnerSigningKeySet = SigningKeySet
