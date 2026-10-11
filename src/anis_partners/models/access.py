"""Verified current state returned by partner self-service stops."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from anis_partners.models._json import field, identifier, model_json, object_data, text, timestamp


@dataclass(frozen=True, slots=True)
class ApplicationSuspended:
    """Retain the application identity and suspension time from the signed answer."""

    application_id: UUID
    status: str | None
    suspended_at: datetime | None

    @classmethod
    def from_json(cls, data: object) -> "ApplicationSuspended":
        """Read the current suspension state, including repeat stop answers."""
        value = object_data(data)
        return cls(
            identifier(field(value, "applicationId")),
            text(field(value, "status")),
            timestamp(field(value, "suspendedAt")),
        )

    def to_json(self) -> dict[str, object]:
        """Write the public camelCase state members."""
        return model_json(self)


@dataclass(frozen=True, slots=True)
class KeyRevoked:
    """Retain the key identity and irreversible revocation time from the signed answer."""

    key_id: UUID
    status: str | None
    revoked_at: datetime | None

    @classmethod
    def from_json(cls, data: object) -> "KeyRevoked":
        """Read the current revocation state, including repeat stop answers."""
        value = object_data(data)
        return cls(
            identifier(field(value, "keyId")), text(field(value, "status")), timestamp(field(value, "revokedAt"))
        )

    def to_json(self) -> dict[str, object]:
        """Write the public camelCase state members."""
        return model_json(self)
