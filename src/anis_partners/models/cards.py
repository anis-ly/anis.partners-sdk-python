"""Masked card projections and protected credential responses."""

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date, datetime
from uuid import UUID

from anis_partners.models._json import (
    boolean,
    calendar_date,
    field,
    identifier,
    integer,
    model_json,
    object_data,
    text,
    timestamp,
)
from anis_partners.models.catalogue import LocalizedText
from anis_partners.models.money import Money


@dataclass(frozen=True, slots=True)
class MaskedCardSubcategory:
    """Identify the sold card's subcategory without exposing credential data."""

    id: UUID = dataclass_field(default_factory=lambda: UUID(int=0))
    name: LocalizedText | None = None

    @classmethod
    def from_json(cls, data: object) -> "MaskedCardSubcategory":
        """Read the optional subcategory label so callers can display older projections too."""
        value = object_data(data)
        name = field(value, "name")
        return cls(
            identifier(field(value, "id")),
            LocalizedText.from_json(name) if name is not None else None,
        )

    def to_json(self) -> dict[str, object]:
        """Write the exact camelCase card projection members."""
        return model_json(self)


@dataclass(frozen=True, slots=True)
class MaskedCardProduct:
    """Identify a catalogue card without attaching its secret credential."""

    id: UUID = dataclass_field(default_factory=lambda: UUID(int=0))
    name: LocalizedText | None = None

    @classmethod
    def from_json(cls, data: object) -> "MaskedCardProduct":
        """Read the catalogue identity and optional label from a masked projection."""
        value = object_data(data)
        name = field(value, "name")
        return cls(
            identifier(field(value, "id")),
            LocalizedText.from_json(name) if name is not None else None,
        )

    def to_json(self) -> dict[str, object]:
        """Write the exact camelCase product projection."""
        return model_json(self)


@dataclass(frozen=True, slots=True)
class MaskedCard:
    """Expose sale and reveal eligibility without placing credential plaintext in list responses."""

    id: UUID = dataclass_field(default_factory=lambda: UUID(int=0))
    order_operation_id: UUID | None = None
    invoice_id: UUID | None = None
    card: MaskedCardProduct | None = None
    serial_number_masked: str | None = None
    credential_available: bool = False
    purchased_at: datetime | None = None
    unit_price: Money | None = None
    expiry_date: date | None = None
    invoice_number: int | None = None
    face_value: str | None = None
    subcategory: MaskedCardSubcategory | None = None

    @classmethod
    def from_json(cls, data: object) -> "MaskedCard":
        """Read optional newer card fields without turning their absence into invented values."""
        value = object_data(data)
        card = field(value, "card")
        unit_price = field(value, "unitPrice")
        subcategory = field(value, "subcategory")
        return cls(
            identifier(field(value, "id")),
            identifier(field(value, "orderOperationId"), optional=True),
            identifier(field(value, "invoiceId"), optional=True),
            MaskedCardProduct.from_json(card) if card is not None else None,
            text(field(value, "serialNumberMasked")),
            boolean(field(value, "credentialAvailable")),
            timestamp(field(value, "purchasedAt")),
            Money.from_json(unit_price) if unit_price is not None else None,
            calendar_date(field(value, "expiryDate")),
            integer(field(value, "invoiceNumber")) if field(value, "invoiceNumber") is not None else None,
            text(field(value, "faceValue")),
            MaskedCardSubcategory.from_json(subcategory) if subcategory is not None else None,
        )

    def to_json(self) -> dict[str, object]:
        """Serialize a masked projection without introducing plaintext credential fields."""
        return model_json(self)


@dataclass(frozen=True, slots=True)
class RevealedCredential:
    """Hold the only credential-plaintext model so hosts can treat it as a secret."""

    sold_card_id: UUID = dataclass_field(default_factory=lambda: UUID(int=0))
    serial_number: str | None = dataclass_field(default=None, repr=False)
    voucher: str | None = dataclass_field(default=None, repr=False)
    revealed_at: datetime | None = None
    expiry_date: date | None = None
    invoice_id: UUID | None = None
    card: MaskedCardProduct | None = None
    purchased_at: datetime | None = None

    @classmethod
    def from_json(cls, data: object) -> "RevealedCredential":
        """Read protected credential fields only from the verified reveal or completion response."""
        value = object_data(data)
        card = field(value, "card")
        return cls(
            identifier(field(value, "soldCardId")),
            text(field(value, "serialNumber")),
            text(field(value, "voucher")),
            timestamp(field(value, "revealedAt")),
            calendar_date(field(value, "expiryDate")),
            identifier(field(value, "invoiceId"), optional=True),
            MaskedCardProduct.from_json(card) if card is not None else None,
            timestamp(field(value, "purchasedAt")),
        )

    def to_json(self) -> dict[str, object]:
        """Return the wire value for deliberate storage; never interpolate this model into logs."""
        return model_json(self)

    def __str__(self) -> str:
        """Redact secrets even when a host accidentally formats a credential for diagnostics."""
        return f"RevealedCredential(sold_card_id={self.sold_card_id}, secret=<redacted>)"

    def __repr__(self) -> str:
        """Keep native inspection useful while replacing credential fields with an explicit redaction marker."""
        return f"RevealedCredential(sold_card_id={self.sold_card_id!r}, serial_number=<redacted>, voucher=<redacted>)"


@dataclass(frozen=True, slots=True)
class RevealedCredentialCollection:
    """Group invoice credentials as an all-or-none verified response."""

    items: tuple[RevealedCredential, ...] = ()

    @classmethod
    def from_json(cls, data: object) -> "RevealedCredentialCollection":
        """Read every returned credential together so invoice reveal is not partially represented."""
        value = object_data(data)
        items = field(value, "items")
        if items is None:
            return cls()
        if not isinstance(items, list):
            raise ValueError("Credential collection items must be a JSON array.")
        return cls(tuple(RevealedCredential.from_json(item) for item in items))

    def to_json(self) -> dict[str, object]:
        """Serialize all credentials as one collection as the invoice reveal route returns them."""
        return model_json(self)
