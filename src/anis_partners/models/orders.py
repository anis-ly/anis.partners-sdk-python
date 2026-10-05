"""Order request, status, and matchable outcome models."""

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, TypeAlias
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
    timestamp,
)
from anis_partners.models.cards import RevealedCredential
from anis_partners.models.money import Money

if TYPE_CHECKING:
    from anis_partners.errors import AnisApiError


class OrderStatus(StrEnum):
    """Preserve future order states without guessing whether an unknown state is a failure."""

    UNKNOWN = "unknown"
    PROCESSING = "processing"
    RECOVERY_EXHAUSTED = "recoveryExhausted"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CreateOrderRequest:
    """Keep the closed order body and exact decimal prices required by the gateway."""

    card_id: UUID
    quantity: int
    expected_unit_price: Money
    expected_total: Money
    external_reference: str | None = None
    use_allowed_debt: bool = False

    @classmethod
    def from_json(cls, data: object) -> "CreateOrderRequest":
        """Read caller-provided prices instead of recomputing a second pricing authority."""
        value = object_data(data)
        card_id = field(value, "cardId")
        quantity = field(value, "quantity")
        unit = field(value, "expectedUnitPrice")
        total = field(value, "expectedTotal")
        if card_id is None or quantity is None or unit is None or total is None:
            raise ValueError("Create-order requests require cardId, quantity, expectedUnitPrice, and expectedTotal.")
        return cls(
            identifier(card_id),
            integer(quantity),
            Money.from_json(unit),
            Money.from_json(total),
            text(field(value, "externalReference")),
            boolean(field(value, "useAllowedDebt")),
        )

    def to_json(self) -> dict[str, object]:
        """Omit a missing external reference because null is not a sent request member."""
        return model_json(self)


@dataclass(frozen=True, slots=True)
class Order:
    """Represent stored order state while keeping released credentials nullable and one-time."""

    operation_id: UUID = dataclass_field(default_factory=lambda: UUID(int=0))
    status: OrderStatus = OrderStatus.UNKNOWN
    invoice_id: UUID | None = None
    wallet_id: UUID | None = None
    card_id: UUID | None = None
    quantity: int | None = None
    total: Money | None = None
    sold_cards: tuple[RevealedCredential, ...] | None = None
    completed_at: datetime | None = None
    external_reference: str | None = None
    failure_code: str | None = None
    codes_withheld: bool | None = None

    @classmethod
    def from_json(cls, data: object) -> "Order":
        """Read status leniently and leave absent response members unset instead of inventing facts."""
        value = object_data(data)
        quantity = field(value, "quantity")
        total = field(value, "total")
        sold_cards = field(value, "soldCards")
        if sold_cards is not None and not isinstance(sold_cards, list):
            raise ValueError("soldCards must be a JSON array or null.")
        return cls(
            identifier(field(value, "operationId")),
            lenient_enum(OrderStatus, field(value, "status"), OrderStatus.UNKNOWN),
            identifier(field(value, "invoiceId"), optional=True),
            identifier(field(value, "walletId"), optional=True),
            identifier(field(value, "cardId"), optional=True),
            integer(quantity) if quantity is not None else None,
            Money.from_json(total) if total is not None else None,
            tuple(RevealedCredential.from_json(item) for item in sold_cards) if sold_cards is not None else None,
            timestamp(field(value, "completedAt")),
            text(field(value, "externalReference")),
            text(field(value, "failureCode")),
            boolean(field(value, "codesWithheld")) if field(value, "codesWithheld") is not None else None,
        )

    def to_json(self) -> dict[str, object]:
        """Serialize only model state; credentials remain present solely when the verified answer carried them."""
        return model_json(self)


@dataclass(frozen=True, slots=True)
class OrderCompleted:
    """Mark credential-bearing completion as a distinct outcome so it cannot be mistaken for a replay."""

    order: Order

    @property
    def operation_id(self) -> UUID:
        """Expose the caller's operation identity for safe correlation and persistence."""
        return self.order.operation_id

    @property
    def credentials(self) -> tuple[RevealedCredential, ...]:
        """Return the credentials released on this first completion; later reads require reveal permission."""
        return self.order.sold_cards or ()

    @property
    def codes_withheld(self) -> bool:
        """Prevent a paid completion with withheld codes from being retried as a new purchase."""
        return self.order.codes_withheld is True or not self.credentials


@dataclass(frozen=True, slots=True)
class OrderProcessing:
    """Represent an admitted order that still needs same-id resumption after its server delay."""

    order: Order
    retry_after: timedelta
    location: str | None = None

    @property
    def operation_id(self) -> UUID:
        """Expose the operation id that must remain stable while processing continues."""
        return self.order.operation_id


@dataclass(frozen=True, slots=True)
class OrderReplayed:
    """Mark a recorded outcome so callers do not expect the replay to carry credentials again."""

    order: Order

    @property
    def operation_id(self) -> UUID:
        """Expose the same operation id whose answer Anis has already recorded."""
        return self.order.operation_id


@dataclass(frozen=True, slots=True)
class OrderOutcomeUnknown:
    """Keep uncertain purchases open so callers resume the same intent instead of buying twice."""

    operation_id: UUID
    suggested_delay: timedelta
    cause: Exception


@dataclass(frozen=True, slots=True)
class OrderNotPlaced:
    """Represent a final refusal so the caller can fix it before creating a new operation id."""

    operation_id: UUID
    refusal: "AnisApiError"


OrderResult: TypeAlias = OrderCompleted | OrderProcessing | OrderReplayed | OrderNotPlaced | OrderOutcomeUnknown
