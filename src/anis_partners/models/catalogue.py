"""Catalogue projections; optional owner copy stays optional and unknown enum values stay readable."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import StrEnum
from typing import Generic, TypeVar, cast
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
)
from anis_partners.models.money import Money


@dataclass(frozen=True, slots=True)
class LocalizedText:
    """Keep owner supplied copy per language because the gateway does not invent a missing translation."""

    ar: str | None = None
    en: str | None = None

    @classmethod
    def from_json(cls, data: object) -> "LocalizedText":
        """Read either language independently so older responses may omit either one."""
        value = object_data(data)
        return cls(text(field(value, "ar")), text(field(value, "en")))

    def to_json(self) -> dict[str, object]:
        """Preserve the contract's short Arabic and English member names."""
        return model_json(self)


class CatalogueCategoryType(StrEnum):
    """Represent category source without failing when Anis adds a future source type."""

    UNKNOWN = "unknown"
    LOCAL = "local"
    INTERNATIONAL = "international"


@dataclass(frozen=True, slots=True)
class CatalogueCategory:
    """Describe a published category while retaining unknown category types for forward compatibility."""

    id: UUID = dataclass_field(default_factory=lambda: UUID(int=0))
    name: LocalizedText | None = None
    description: LocalizedText | None = None
    logo: str | None = None
    type: CatalogueCategoryType = CatalogueCategoryType.UNKNOWN
    in_stock: bool = False
    display_order: int = 0

    @classmethod
    def from_json(cls, data: object) -> "CatalogueCategory":
        """Read a category without rejecting new enum values or absent optional copy."""
        value = object_data(data)
        name = field(value, "name")
        description = field(value, "description")
        return cls(
            identifier(field(value, "id")),
            LocalizedText.from_json(name) if name is not None else None,
            LocalizedText.from_json(description) if description is not None else None,
            text(field(value, "logo")),
            lenient_enum(CatalogueCategoryType, field(value, "type"), CatalogueCategoryType.UNKNOWN),
            boolean(field(value, "inStock")),
            integer(field(value, "displayOrder")),
        )

    def to_json(self) -> dict[str, object]:
        """Write camelCase names exactly as the catalogue response uses them."""
        return model_json(self)


@dataclass(frozen=True, slots=True)
class CatalogueSubcategory:
    """Preserve purchase guidance and availability so partners can show the terms before a sale."""

    id: UUID = dataclass_field(default_factory=lambda: UUID(int=0))
    category_id: UUID = dataclass_field(default_factory=lambda: UUID(int=0))
    name: LocalizedText | None = None
    description: LocalizedText | None = None
    logo: str | None = None
    is_best_selling: bool = False
    display_order: int = 0
    available: bool = False
    disclaimer: LocalizedText | None = None

    @classmethod
    def from_json(cls, data: object) -> "CatalogueSubcategory":
        """Read optional disclaimer and display members so older catalogue answers remain usable."""
        value = object_data(data)
        nested = {name: field(value, name) for name in ("name", "description", "disclaimer")}
        return cls(
            identifier(field(value, "id")),
            identifier(field(value, "categoryId")),
            LocalizedText.from_json(nested["name"]) if nested["name"] is not None else None,
            LocalizedText.from_json(nested["description"]) if nested["description"] is not None else None,
            text(field(value, "logo")),
            boolean(field(value, "isBestSelling")),
            integer(field(value, "displayOrder")),
            boolean(field(value, "available")),
            LocalizedText.from_json(nested["disclaimer"]) if nested["disclaimer"] is not None else None,
        )

    def to_json(self) -> dict[str, object]:
        """Write the contract's camelCase subcategory shape."""
        return model_json(self)


@dataclass(frozen=True, slots=True)
class CatalogueCard:
    """Expose wallet-specific prices unchanged because Anis validates orders against the catalogue price."""

    id: UUID = dataclass_field(default_factory=lambda: UUID(int=0))
    subcategory_id: UUID = dataclass_field(default_factory=lambda: UUID(int=0))
    name: LocalizedText | None = None
    face_value: str | None = None
    unit_price: Money | None = None
    business_price: Money | None = None
    personal_price: Money | None = None
    has_special_offer: bool = False
    special_offer_price: Money | None = None
    available: bool = False
    minimum_quantity: int | None = None
    maximum_quantity: int | None = None

    @classmethod
    def from_json(cls, data: object) -> "CatalogueCard":
        """Read each price separately so display-only prices cannot replace the order's expected unit price."""
        value = object_data(data)
        name = field(value, "name")
        money_fields = {
            name: Money.from_json(field(value, name)) if field(value, name) is not None else None
            for name in ("unitPrice", "businessPrice", "personalPrice", "specialOfferPrice")
        }
        return cls(
            identifier(field(value, "id")),
            identifier(field(value, "subcategoryId")),
            LocalizedText.from_json(name) if name is not None else None,
            text(field(value, "faceValue")),
            money_fields["unitPrice"],
            money_fields["businessPrice"],
            money_fields["personalPrice"],
            boolean(field(value, "hasSpecialOffer")),
            money_fields["specialOfferPrice"],
            boolean(field(value, "available")),
            integer(field(value, "minimumQuantity")) if field(value, "minimumQuantity") is not None else None,
            integer(field(value, "maximumQuantity")) if field(value, "maximumQuantity") is not None else None,
        )

    def to_json(self) -> dict[str, object]:
        """Write nested money values as decimal strings in the gateway's camelCase form."""
        return model_json(self)


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    """Carry a cursor so callers can continue the exact paged read without guessing offsets."""

    items: tuple[T, ...] = ()
    next_cursor: str | None = None

    @classmethod
    def from_json(cls, data: object, item_reader: Callable[[object], T] | None = None) -> "Page[T]":
        """Decode page items with their route model while preserving the server's continuation cursor."""
        value = object_data(data)
        raw_items = field(value, "items")
        if raw_items is None:
            raw_items = []
        if not isinstance(raw_items, list):
            raise ValueError("Page items must be a JSON array.")
        if item_reader is not None:
            items = tuple(item_reader(item) for item in raw_items)
        else:
            items = cast(tuple[T, ...], tuple(raw_items))
        return cls(items, text(field(value, "nextCursor")))

    def to_json(self) -> dict[str, object]:
        """Serialize items and cursor without renaming contract members."""
        return model_json(self)
