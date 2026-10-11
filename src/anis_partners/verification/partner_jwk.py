"""Parse rotating public keys and reject malformed material before it can authenticate a response."""

import json
from dataclasses import dataclass, field
from datetime import datetime

from cryptography.hazmat.primitives.asymmetric import ec

from anis_partners._internal.base64url import decode
from anis_partners.models._json import object_data, text, timestamp


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
    d: str | None = field(default=None, repr=False)

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


def _lifecycle_date(value: object) -> datetime | None:
    """Keep invalid lifecycle dates unavailable so the matched key fails with key_rejected."""
    try:
        return timestamp(value)
    except (ValueError, TypeError, OverflowError):
        return None


@dataclass(frozen=True, slots=True)
class PublishedSigningKey(PartnerJwk):
    """Attach the signing lifecycle without loosening enrollment's public JWK."""

    status: str | None = None
    not_before: datetime | None = None
    retired_at: datetime | None = None

    @classmethod
    def from_json(cls, data: object) -> "PublishedSigningKey":
        """Read lifecycle timestamps used to reject signatures outside a version's signing window."""
        value = object_data(data)
        jwk = PartnerJwk.from_json(value)
        raw_status = value.get("status")
        status = raw_status if isinstance(raw_status, str) else None
        not_before = _lifecycle_date(value.get("notBefore"))
        retired_at = _lifecycle_date(value.get("retiredAt"))
        return cls(jwk.kty, jwk.crv, jwk.x, jwk.y, jwk.kid, jwk.use, jwk.alg, jwk.d, status, not_before, retired_at)

    def to_json(self) -> dict[str, object]:
        """Preserve lifecycle metadata when a published key is serialized."""
        from anis_partners.models._json import wire_timestamp

        value = PartnerJwk.to_json(self)
        if self.status is not None:
            value["status"] = self.status
        if self.not_before is not None:
            value["notBefore"] = wire_timestamp(self.not_before)
        if self.retired_at is not None:
            value["retiredAt"] = wire_timestamp(self.retired_at)
        return value


@dataclass(frozen=True, slots=True)
class RevokedSigningKey:
    """Identify a compromised version independently from available public keys."""

    kid: str
    compromised_at: datetime

    @classmethod
    def from_json(cls, data: object) -> "RevokedSigningKey":
        """Require the identity and compromise timestamp from each revocation entry."""
        value = object_data(data)
        kid = text(value.get("kid"))
        compromised_at = timestamp(value.get("compromisedAt"))
        if not kid or compromised_at is None:
            raise ValueError("Revoked keys require kid and compromisedAt.")
        return cls(kid, compromised_at)


@dataclass(frozen=True, slots=True)
class SigningKeySet:
    """Retain rotation versions together so responses issued just before or after rotation remain verifiable."""

    #: Active, next, and retired keys needed to verify responses across a rotation boundary.
    keys: tuple[PublishedSigningKey, ...] = ()
    revoked: tuple[RevokedSigningKey, ...] = ()

    @classmethod
    def from_json(cls, document: str | bytes) -> "SigningKeySet":
        """Retain private-member disclosure so a compromised or mispublished document is refused as a whole."""
        value = json.loads(document)
        if not isinstance(value, dict) or not isinstance(value.get("keys", []), list):
            raise ValueError("The signing key document must contain a keys array.")
        parsed_keys = [PublishedSigningKey.from_json(item) for item in value.get("keys", [])]
        revoked = value.get("revoked", [])
        if not isinstance(revoked, list):
            raise ValueError("The signing key document revoked member must be an array.")
        return cls(tuple(parsed_keys), tuple(RevokedSigningKey.from_json(item) for item in revoked))


PartnerSigningKeySet = SigningKeySet
