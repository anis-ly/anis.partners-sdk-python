"""Partner, application, owner, and wallet projections."""

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from decimal import Decimal
from uuid import UUID

from anis_partners.models._json import field, identifier, model_json, object_data, text
from anis_partners.models.money import Money


@dataclass(frozen=True, slots=True)
class Wallet:
    """Represent a wallet only after the API confirms this application may act on it."""

    id: UUID = dataclass_field(default_factory=lambda: UUID(int=0))
    name: str | None = None
    currency: str | None = None
    balance: Money = dataclass_field(default_factory=lambda: Money(Decimal("0.000"), ""))

    @classmethod
    def from_json(cls, data: object) -> "Wallet":
        """Read the reserved-adjusted balance from the server instead of inferring it locally."""
        value = object_data(data)
        balance = field(value, "balance")
        return cls(
            identifier(field(value, "id")),
            text(field(value, "name")),
            text(field(value, "currency")),
            Money.from_json(balance) if balance is not None else Money.from_json({"amount": "0.000", "currency": ""}),
        )

    def to_json(self) -> dict[str, object]:
        """Write the exact wallet projection, including its server-reported balance."""
        return model_json(self)


@dataclass(frozen=True, slots=True)
class PartnerIdentity:
    """Identify the partner without copying display or environment data into the SDK model."""

    id: UUID = dataclass_field(default_factory=lambda: UUID(int=0))

    @classmethod
    def from_json(cls, data: object) -> "PartnerIdentity":
        """Read the durable partner id used for correlation."""
        value = object_data(data)
        return cls(identifier(field(value, "id")))

    def to_json(self) -> dict[str, object]:
        """Write the same principal id so policy correlation does not drift across a profile round trip."""
        return model_json(self)


@dataclass(frozen=True, slots=True)
class ApplicationIdentity:
    """Represent the application principal whose policy scopes can change between calls."""

    id: UUID = dataclass_field(default_factory=lambda: UUID(int=0))
    scopes: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, data: object) -> "ApplicationIdentity":
        """Read effective scopes from each response because policy changes take effect per request."""
        value = object_data(data)
        scopes = field(value, "scopes")
        if scopes is None:
            scopes = []
        if not isinstance(scopes, list) or any(not isinstance(scope, str) for scope in scopes):
            raise ValueError("Application scopes must be a JSON array of strings.")
        return cls(identifier(field(value, "id")), tuple(scopes))

    def to_json(self) -> dict[str, object]:
        """Preserve the currently effective scope names instead of deriving access from cached policy."""
        return model_json(self)


@dataclass(frozen=True, slots=True)
class OwnerAccount:
    """Identify the owner behind wallet business rules without exposing unrelated owner state."""

    id: UUID = dataclass_field(default_factory=lambda: UUID(int=0))
    display_name: str | None = None

    @classmethod
    def from_json(cls, data: object) -> "OwnerAccount":
        """Read the account identity and optional display label from the profile projection."""
        value = object_data(data)
        return cls(identifier(field(value, "id")), text(field(value, "displayName")))

    def to_json(self) -> dict[str, object]:
        """Keep account identity stable so wallet and support records refer to the same owner."""
        return model_json(self)


@dataclass(frozen=True, slots=True)
class PartnerProfile:
    """Expose effective identity and policy context without inventing an environment selector."""

    partner: PartnerIdentity | None = None
    application: ApplicationIdentity | None = None
    owner_account: OwnerAccount | None = None
    documentation_version: str | None = None

    @classmethod
    def from_json(cls, data: object) -> "PartnerProfile":
        """Read optional identity projections so profile additions do not break existing hosts."""
        value = object_data(data)
        partner = field(value, "partner")
        application = field(value, "application")
        account = field(value, "ownerAccount")
        return cls(
            PartnerIdentity.from_json(partner) if partner is not None else None,
            ApplicationIdentity.from_json(application) if application is not None else None,
            OwnerAccount.from_json(account) if account is not None else None,
            text(field(value, "documentationVersion")),
        )

    def to_json(self) -> dict[str, object]:
        """Write the profile's optional identity members without inventing deployment-specific fields."""
        return model_json(self)
