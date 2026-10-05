"""Enrollment answers and requests, including the fields required to prove key possession."""

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime
from uuid import UUID

from anis_partners.models._json import (
    field,
    identifier,
    integer,
    model_json,
    object_data,
    text,
    timestamp,
)
from anis_partners.verification.partner_jwk import PartnerJwk


@dataclass(frozen=True, slots=True)
class EnrollmentState:
    """Represent invitation state without requiring newer optional identity fields."""

    invitation_id: UUID | None = None
    application_id: UUID | None = None
    state: str | None = None
    expires_at: datetime | None = None

    @classmethod
    def from_json(cls, data: object) -> "EnrollmentState":
        """Read invitation timing and identity when present so omitted fields remain distinguishable."""
        value = object_data(data)
        return cls(
            identifier(field(value, "invitationId"), optional=True),
            identifier(field(value, "applicationId"), optional=True),
            text(field(value, "state")),
            timestamp(field(value, "expiresAt")),
        )

    def to_json(self) -> dict[str, object]:
        """Write camelCase names so returned enrollment state can be preserved without schema drift."""
        return model_json(self)


@dataclass(frozen=True, slots=True)
class EnrollmentKeyRequest:
    """Carry only the public JWK because sending its private scalar would disclose the credential."""

    public_jwk: PartnerJwk
    not_before: datetime
    expires_at: datetime

    @classmethod
    def from_json(cls, data: object) -> "EnrollmentKeyRequest":
        """Read the requested validity window as aware instants to avoid local-time ambiguity."""
        value = object_data(data)
        public_jwk = field(value, "publicJwk")
        not_before = timestamp(field(value, "notBefore"))
        expires_at = timestamp(field(value, "expiresAt"))
        if public_jwk is None or not_before is None or expires_at is None:
            raise ValueError("Enrollment key requests require a public JWK and validity window.")
        return cls(PartnerJwk.from_json(public_jwk), not_before, expires_at)

    def to_json(self) -> dict[str, object]:
        """Write validity timestamps in UTC and the public key in its contract representation."""
        return model_json(self)


@dataclass(frozen=True, slots=True)
class EnrollmentKeyResult:
    """Keep the server key id and proof challenge together so a proof answers the right generation."""

    key_id: UUID = dataclass_field(default_factory=lambda: UUID(int=0))
    thumbprint: str | None = None
    safety_code: str | None = None
    challenge: str | None = None
    challenge_generation: int | None = None

    @classmethod
    def from_json(cls, data: object) -> "EnrollmentKeyResult":
        """Read exactly the published answer members without treating optional challenge fields as errors."""
        value = object_data(data)
        generation = field(value, "challengeGeneration")
        return cls(
            identifier(field(value, "keyId")),
            text(field(value, "thumbprint")),
            text(field(value, "safetyCode")),
            text(field(value, "challenge")),
            integer(generation) if generation is not None else None,
        )

    def to_json(self) -> dict[str, object]:
        """Write the exact answer keys so a proof request keeps its server-issued challenge identity."""
        return model_json(self)


@dataclass(frozen=True, slots=True)
class EnrollmentProofRequest:
    """Bind the proof signature to the key and current challenge generation."""

    key_id: UUID
    challenge_generation: int
    signature: str

    @classmethod
    def from_json(cls, data: object) -> "EnrollmentProofRequest":
        """Read challenge generation explicitly because proofs for an older generation are refused."""
        value = object_data(data)
        key_id = field(value, "keyId")
        generation = field(value, "challengeGeneration")
        signature = field(value, "signature")
        if key_id is None or generation is None or signature is None:
            raise ValueError("Enrollment proof requests require keyId, challengeGeneration, and signature.")
        return cls(
            identifier(key_id),
            integer(generation),
            text(signature) or "",
        )

    def to_json(self) -> dict[str, object]:
        """Write the key and generation together so Anis can reject stale proof submissions."""
        return model_json(self)


@dataclass(frozen=True, slots=True)
class EnrollmentStatus:
    """Expose proof and staff approval as separate states so pending approval is not mistaken for activation."""

    key_id: UUID | None = None
    challenge_generation: int | None = None
    proof_state: str | None = None
    approval_state: str | None = None
    state: str | None = None
    expires_at: datetime | None = None
    key_expires_at: datetime | None = None

    @classmethod
    def from_json(cls, data: object) -> "EnrollmentStatus":
        """Read optional expiry and approval details so callers do not infer state transitions."""
        value = object_data(data)
        generation = field(value, "challengeGeneration")
        return cls(
            identifier(field(value, "keyId"), optional=True),
            integer(generation) if generation is not None else None,
            text(field(value, "proofState")),
            text(field(value, "approvalState")),
            text(field(value, "state")),
            timestamp(field(value, "expiresAt")),
            timestamp(field(value, "keyExpiresAt")),
        )

    def to_json(self) -> dict[str, object]:
        """Preserve approval separately from proof state so hosts cannot mistake pending approval for active."""
        return model_json(self)


@dataclass(frozen=True, slots=True)
class SignatureDiagnostic:
    """Capture gateway-side signature facts so partners can diagnose a mismatch without exposing signed bytes."""

    route_id: str | None = None
    method: str | None = None
    authority: str | None = None
    path: str | None = None
    canonical_query: str | None = None
    request_kind: str | None = None
    required_scope: str | None = None
    covered_components: tuple[str, ...] = ()
    key_id: UUID | None = None
    partner_id: UUID | None = None
    application_id: UUID | None = None
    policy_version: int | None = None
    effective_scopes: tuple[str, ...] = ()
    received_at: datetime | None = None

    @classmethod
    def from_json(cls, data: object) -> "SignatureDiagnostic":
        """Read the gateway's canonical facts so a partner can compare them with its own request."""
        value = object_data(data)
        covered = field(value, "coveredComponents")
        scopes = field(value, "effectiveScopes")
        if covered is None:
            covered = []
        if scopes is None:
            scopes = []
        if not isinstance(covered, list) or any(not isinstance(item, str) for item in covered):
            raise ValueError("coveredComponents must be an array of strings.")
        if not isinstance(scopes, list) or any(not isinstance(item, str) for item in scopes):
            raise ValueError("effectiveScopes must be an array of strings.")
        version = field(value, "policyVersion")
        return cls(
            text(field(value, "routeId")),
            text(field(value, "method")),
            text(field(value, "authority")),
            text(field(value, "path")),
            text(field(value, "canonicalQuery")),
            text(field(value, "requestKind")),
            text(field(value, "requiredScope")),
            tuple(covered),
            identifier(field(value, "keyId"), optional=True),
            identifier(field(value, "partnerId"), optional=True),
            identifier(field(value, "applicationId"), optional=True),
            integer(version) if version is not None else None,
            tuple(scopes),
            timestamp(field(value, "receivedAt")),
        )

    def to_json(self) -> dict[str, object]:
        """Keep gateway diagnostics in the documented shape without copying signature secrets into the model."""
        return model_json(self)
