"""Immutable direct recharge products wire models."""

import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import StrEnum
from uuid import UUID

from anis_partners.models._json import (
    boolean,
    field,
    identifier,
    integer,
    lenient_enum,
    model_json,
    object_data,
    text,
    wire_value,
)
from anis_partners.models.catalogue import LocalizedText
from anis_partners.models.money import Money


class DirectRechargeProductType(StrEnum):
    UNKNOWN = "unknown"
    EXTERNAL = "external"
    BILLING = "billing"


class DirectRechargeFieldKind(StrEnum):
    UNKNOWN = "unknown"
    TEXT = "text"
    LIST = "list"
    NOTE = "note"


class DirectRechargeFieldFor(StrEnum):
    UNKNOWN = "unknown"
    RECIPIENT = "recipient"
    SENDER = "sender"


class DirectRechargeAmountIn(StrEnum):
    UNKNOWN = "unknown"
    LYD = "lyd"
    FX = "fx"


@dataclass(frozen=True, slots=True)
class DirectRechargeCurrency:
    name: str

    @classmethod
    def from_json(cls, data: object) -> "DirectRechargeCurrency":
        value = object_data(data)
        if any(key not in value or value[key] is None for key in ("name",)):
            raise ValueError("DirectRechargeCurrency is missing a required member.")
        return cls(
            text(field(value, "name"), "") or "",
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        return result


@dataclass(frozen=True, slots=True)
class DirectRechargePayout:
    amount: str
    currency: DirectRechargeCurrency

    def __post_init__(self) -> None:
        if not isinstance(self.amount, str) or not re.fullmatch(r"[0-9]+\.[0-9]{3}", self.amount):
            raise ValueError("Payout must be a decimal string with three fractional digits.")

    @classmethod
    def from_json(cls, data: object) -> "DirectRechargePayout":
        value = object_data(data)
        if any(key not in value or value[key] is None for key in ("amount", "currency")):
            raise ValueError("DirectRechargePayout is missing a required member.")
        return cls(
            text(field(value, "amount"), "") or "",
            DirectRechargeCurrency.from_json(field(value, "currency")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        return result


@dataclass(frozen=True, slots=True)
class DirectRechargeCategory:
    id: UUID
    name: str
    icon: str | None = None

    @classmethod
    def from_json(cls, data: object) -> "DirectRechargeCategory":
        value = object_data(data)
        if any(key not in value or value[key] is None for key in ("id", "name")):
            raise ValueError("DirectRechargeCategory is missing a required member.")
        return cls(
            identifier(field(value, "id")),
            text(field(value, "name"), "") or "",
            text(field(value, "icon")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        return result


@dataclass(frozen=True, slots=True)
class DirectRechargeLimits:
    minimum_total: Money | None = None
    maximum_total: Money | None = None
    minimum_payout: str | None = None
    maximum_payout: str | None = None

    @classmethod
    def from_json(cls, data: object) -> "DirectRechargeLimits":
        value = object_data(data)
        return cls(
            Money.from_json(field(value, "minimumTotal")) if field(value, "minimumTotal") is not None else None,
            Money.from_json(field(value, "maximumTotal")) if field(value, "maximumTotal") is not None else None,
            text(field(value, "minimumPayout")),
            text(field(value, "maximumPayout")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        return result


@dataclass(frozen=True, slots=True)
class DirectRechargeRecipientField:
    key: str
    name: LocalizedText | None
    kind: DirectRechargeFieldKind
    for_: DirectRechargeFieldFor
    order: int
    validation: str | None = dataclass_field(default=None, repr=False)
    validation_message: LocalizedText | None = dataclass_field(default=None, repr=False)
    raw_kind: str | None = dataclass_field(default=None, repr=False)
    raw_for_: str | None = dataclass_field(default=None, repr=False)

    @classmethod
    def from_json(cls, data: object) -> "DirectRechargeRecipientField":
        value = object_data(data)
        if any(key not in value or value[key] is None for key in ("key", "kind", "for", "order")):
            raise ValueError("DirectRechargeRecipientField is missing a required member.")
        return cls(
            text(field(value, "key"), "") or "",
            LocalizedText.from_json(field(value, "name")) if field(value, "name") is not None else None,
            lenient_enum(DirectRechargeFieldKind, field(value, "kind"), DirectRechargeFieldKind.UNKNOWN),
            lenient_enum(DirectRechargeFieldFor, field(value, "for"), DirectRechargeFieldFor.UNKNOWN),
            integer(field(value, "order")),
            text(field(value, "validation")),
            LocalizedText.from_json(field(value, "validationMessage"))
            if field(value, "validationMessage") is not None
            else None,
            text(field(value, "kind")),
            text(field(value, "for")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        result.pop("rawKind", None)
        if self.raw_kind is not None:
            result["kind"] = self.raw_kind
        result.pop("rawFor_", None)
        result.pop("for_", None)
        result["for"] = self.raw_for_ if self.raw_for_ is not None else wire_value(self.for_)
        return result


@dataclass(frozen=True, slots=True)
class DirectRechargeProductSummary:
    id: UUID
    title: str
    type: DirectRechargeProductType
    payout_currency: DirectRechargeCurrency
    available: bool
    description: str | None = None
    category: DirectRechargeCategory | None = None
    limits: DirectRechargeLimits | None = None
    raw_type: str | None = dataclass_field(default=None, repr=False)

    @classmethod
    def from_json(cls, data: object) -> "DirectRechargeProductSummary":
        value = object_data(data)
        if any(
            key not in value or value[key] is None for key in ("id", "title", "type", "payoutCurrency", "available")
        ):
            raise ValueError("DirectRechargeProductSummary is missing a required member.")
        return cls(
            identifier(field(value, "id")),
            text(field(value, "title"), "") or "",
            lenient_enum(DirectRechargeProductType, field(value, "type"), DirectRechargeProductType.UNKNOWN),
            DirectRechargeCurrency.from_json(field(value, "payoutCurrency")),
            boolean(field(value, "available")),
            text(field(value, "description")),
            DirectRechargeCategory.from_json(field(value, "category"))
            if field(value, "category") is not None
            else None,
            DirectRechargeLimits.from_json(field(value, "limits")) if field(value, "limits") is not None else None,
            text(field(value, "type")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        if self.limits is not None:
            result["limits"] = self.limits.to_json()
        result.pop("rawType", None)
        if self.raw_type is not None:
            result["type"] = self.raw_type
        return result


@dataclass(frozen=True, slots=True)
class DirectRechargeProduct:
    id: UUID
    title: str
    type: DirectRechargeProductType
    payout_currency: DirectRechargeCurrency
    available: bool
    recipient_fields: tuple[DirectRechargeRecipientField, ...]
    description: str | None = None
    category: DirectRechargeCategory | None = None
    limits: DirectRechargeLimits | None = None
    raw_type: str | None = dataclass_field(default=None, repr=False)

    @classmethod
    def from_json(cls, data: object) -> "DirectRechargeProduct":
        value = object_data(data)
        if any(
            key not in value or value[key] is None
            for key in ("id", "title", "type", "payoutCurrency", "available", "recipientFields")
        ):
            raise ValueError("DirectRechargeProduct is missing a required member.")
        recipient_fields = field(value, "recipientFields")
        if not isinstance(recipient_fields, list):
            raise ValueError("recipientFields must be a JSON array.")
        return cls(
            identifier(field(value, "id")),
            text(field(value, "title"), "") or "",
            lenient_enum(DirectRechargeProductType, field(value, "type"), DirectRechargeProductType.UNKNOWN),
            DirectRechargeCurrency.from_json(field(value, "payoutCurrency")),
            boolean(field(value, "available")),
            tuple(DirectRechargeRecipientField.from_json(item) for item in recipient_fields),
            text(field(value, "description")),
            DirectRechargeCategory.from_json(field(value, "category"))
            if field(value, "category") is not None
            else None,
            DirectRechargeLimits.from_json(field(value, "limits")) if field(value, "limits") is not None else None,
            text(field(value, "type")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        if self.limits is not None:
            result["limits"] = self.limits.to_json()
        result.pop("rawType", None)
        if self.raw_type is not None:
            result["type"] = self.raw_type
        return result


@dataclass(frozen=True, slots=True)
class DirectRechargeLocation:
    id: UUID
    name: str

    @classmethod
    def from_json(cls, data: object) -> "DirectRechargeLocation":
        value = object_data(data)
        if any(key not in value or value[key] is None for key in ("id", "name")):
            raise ValueError("DirectRechargeLocation is missing a required member.")
        return cls(
            identifier(field(value, "id")),
            text(field(value, "name"), "") or "",
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        return result


@dataclass(frozen=True, slots=True)
class DirectRechargeQuote:
    product_id: UUID
    payout: DirectRechargePayout
    exchange_rate: str
    price: Money
    commission: Money
    total: Money

    @classmethod
    def from_json(cls, data: object) -> "DirectRechargeQuote":
        value = object_data(data)
        if any(
            key not in value or value[key] is None
            for key in ("productId", "payout", "exchangeRate", "price", "commission", "total")
        ):
            raise ValueError("DirectRechargeQuote is missing a required member.")
        return cls(
            identifier(field(value, "productId")),
            DirectRechargePayout.from_json(field(value, "payout")),
            text(field(value, "exchangeRate"), "") or "",
            Money.from_json(field(value, "price")),
            Money.from_json(field(value, "commission")),
            Money.from_json(field(value, "total")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        return result


@dataclass(frozen=True, slots=True)
class DirectRechargeProductsQuery:
    type: DirectRechargeProductType | None = None
    cursor: str | None = None
    raw_type: str | None = dataclass_field(default=None, repr=False)

    @classmethod
    def from_json(cls, data: object) -> "DirectRechargeProductsQuery":
        value = object_data(data)
        return cls(
            lenient_enum(DirectRechargeProductType, field(value, "type"), DirectRechargeProductType.UNKNOWN)
            if field(value, "type") is not None
            else None,
            text(field(value, "cursor")),
            text(field(value, "type")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        result.pop("rawType", None)
        if self.raw_type is not None:
            result["type"] = self.raw_type
        return result


@dataclass(frozen=True, slots=True)
class DirectRechargeLocationsQuery:
    search: str | None = None
    cursor: str | None = None

    @classmethod
    def from_json(cls, data: object) -> "DirectRechargeLocationsQuery":
        value = object_data(data)
        return cls(
            text(field(value, "search")),
            text(field(value, "cursor")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        return result
