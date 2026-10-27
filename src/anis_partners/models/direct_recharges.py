"""Immutable direct recharges wire models."""

import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime
from enum import StrEnum
from typing import cast
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
    wire_value,
)
from anis_partners.models.catalogue import LocalizedText
from anis_partners.models.direct_recharge_products import DirectRechargePayout
from anis_partners.models.money import Money


class DirectRechargeStatus(StrEnum):
    UNKNOWN = "unknown"
    AWAITING_PAYMENT = "awaitingPayment"
    PAYMENT_FAILED = "paymentFailed"
    PENDING = "pending"
    IN_PROGRESS = "inProgress"
    SUSPENDED_DATA_ERROR = "suspendedDataError"
    COMPLETED = "completed"
    REJECTED_AWAITING_REFUND = "rejectedAwaitingRefund"
    REJECTED_WITH_REFUND = "rejectedWithRefund"


@dataclass(frozen=True, slots=True)
class DirectRechargeProductReference:
    id: UUID
    title: str

    @classmethod
    def from_json(cls, data: object) -> "DirectRechargeProductReference":
        value = object_data(data)
        if any(key not in value or value[key] is None for key in ("id", "title")):
            raise ValueError("DirectRechargeProductReference is missing a required member.")
        return cls(
            identifier(field(value, "id")),
            text(field(value, "title"), "") or "",
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        return result


@dataclass(frozen=True, slots=True)
class DirectRechargeRecipientInput:
    key: str
    value: str = dataclass_field(repr=False)

    @classmethod
    def from_json(cls, data: object) -> "DirectRechargeRecipientInput":
        value = object_data(data)
        if any(key not in value or value[key] is None for key in ("key", "value")):
            raise ValueError("DirectRechargeRecipientInput is missing a required member.")
        return cls(
            text(field(value, "key"), "") or "",
            text(field(value, "value"), "") or "",
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        result.update(key=self.key, value=self.value)
        return result


@dataclass(frozen=True, slots=True)
class DirectRechargeRecipientValue:
    key: str
    name: LocalizedText | None
    value: str = dataclass_field(repr=False)
    value_name: str | None = None

    @classmethod
    def from_json(cls, data: object) -> "DirectRechargeRecipientValue":
        value = object_data(data)
        if any(key not in value or value[key] is None for key in ("key", "value")):
            raise ValueError("DirectRechargeRecipientValue is missing a required member.")
        return cls(
            text(field(value, "key"), "") or "",
            LocalizedText.from_json(field(value, "name")) if field(value, "name") is not None else None,
            text(field(value, "value"), "") or "",
            text(field(value, "valueName")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        result.update(key=self.key, value=self.value)
        return result


@dataclass(frozen=True, slots=True)
class CreateDirectRechargeRequest:
    product_id: UUID
    payout_amount: str
    expected_total: Money
    recipient: tuple[DirectRechargeRecipientInput, ...] = dataclass_field(repr=False)
    note: str | None = dataclass_field(default=None, repr=False)
    external_reference: str | None = dataclass_field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.payout_amount, str) or not re.fullmatch(r"[0-9]+\.[0-9]{3}", self.payout_amount):
            raise ValueError("Payout must be a decimal string with three fractional digits.")

    @classmethod
    def from_json(cls, data: object) -> "CreateDirectRechargeRequest":
        value = object_data(data)
        if any(
            key not in value or value[key] is None
            for key in ("productId", "payoutAmount", "expectedTotal", "recipient")
        ):
            raise ValueError("CreateDirectRechargeRequest is missing a required member.")
        recipient = field(value, "recipient")
        if not isinstance(recipient, list):
            raise ValueError("recipient must be a JSON array.")
        return cls(
            identifier(field(value, "productId")),
            text(field(value, "payoutAmount"), "") or "",
            Money.from_json(field(value, "expectedTotal")),
            tuple(DirectRechargeRecipientInput.from_json(item) for item in recipient),
            text(field(value, "note")),
            text(field(value, "externalReference")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        return result


@dataclass(frozen=True, slots=True)
class UpdateDirectRechargeRecipientRequest:
    recipient: tuple[DirectRechargeRecipientInput, ...] = dataclass_field(repr=False)

    @classmethod
    def from_json(cls, data: object) -> "UpdateDirectRechargeRecipientRequest":
        value = object_data(data)
        if any(key not in value or value[key] is None for key in ("recipient",)):
            raise ValueError("UpdateDirectRechargeRecipientRequest is missing a required member.")
        recipient = field(value, "recipient")
        if not isinstance(recipient, list):
            raise ValueError("recipient must be a JSON array.")
        return cls(
            tuple(DirectRechargeRecipientInput.from_json(item) for item in recipient),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        return result


@dataclass(frozen=True, slots=True)
class DirectRechargePartialRefund:
    refunded_payout: str
    refunded_total: Money
    remaining_payout: str
    remaining_total: Money

    @classmethod
    def from_json(cls, data: object) -> "DirectRechargePartialRefund":
        value = object_data(data)
        if any(
            key not in value or value[key] is None
            for key in ("refundedPayout", "refundedTotal", "remainingPayout", "remainingTotal")
        ):
            raise ValueError("DirectRechargePartialRefund is missing a required member.")
        return cls(
            text(field(value, "refundedPayout"), "") or "",
            Money.from_json(field(value, "refundedTotal")),
            text(field(value, "remainingPayout"), "") or "",
            Money.from_json(field(value, "remainingTotal")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        return result


@dataclass(frozen=True, slots=True)
class DirectRecharge:
    operation_id: UUID
    status: DirectRechargeStatus
    number: int
    wallet_id: UUID
    product: DirectRechargeProductReference
    payout: DirectRechargePayout
    exchange_rate: str
    price: Money
    commission: Money
    total: Money
    recipient: tuple[DirectRechargeRecipientValue, ...] = dataclass_field(repr=False)
    requested_at: datetime
    note: str | None = dataclass_field(default=None, repr=False)
    external_reference: str | None = dataclass_field(default=None, repr=False)
    completed_at: datetime | None = None
    proof_url: str | None = dataclass_field(default=None, repr=False)
    reason: str | None = dataclass_field(default=None, repr=False)
    partial_refund: DirectRechargePartialRefund | None = None
    raw_status: str | None = dataclass_field(default=None, repr=False)

    @classmethod
    def from_json(cls, data: object) -> "DirectRecharge":
        value = object_data(data)
        if any(
            key not in value or value[key] is None
            for key in (
                "operationId",
                "status",
                "number",
                "walletId",
                "product",
                "payout",
                "exchangeRate",
                "price",
                "commission",
                "total",
                "recipient",
                "requestedAt",
            )
        ):
            raise ValueError("DirectRecharge is missing a required member.")
        recipient = field(value, "recipient")
        if not isinstance(recipient, list):
            raise ValueError("recipient must be a JSON array.")
        return cls(
            identifier(field(value, "operationId")),
            lenient_enum(DirectRechargeStatus, field(value, "status"), DirectRechargeStatus.UNKNOWN),
            integer(field(value, "number")),
            identifier(field(value, "walletId")),
            DirectRechargeProductReference.from_json(field(value, "product")),
            DirectRechargePayout.from_json(field(value, "payout")),
            text(field(value, "exchangeRate"), "") or "",
            Money.from_json(field(value, "price")),
            Money.from_json(field(value, "commission")),
            Money.from_json(field(value, "total")),
            tuple(DirectRechargeRecipientValue.from_json(item) for item in recipient),
            cast(datetime, timestamp(field(value, "requestedAt"))),
            text(field(value, "note")),
            text(field(value, "externalReference")),
            timestamp(field(value, "completedAt")),
            text(field(value, "proofUrl")),
            text(field(value, "reason")),
            DirectRechargePartialRefund.from_json(field(value, "partialRefund"))
            if field(value, "partialRefund") is not None
            else None,
            text(field(value, "status")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        result.pop("rawStatus", None)
        if self.raw_status is not None:
            result["status"] = self.raw_status
        return result


@dataclass(frozen=True, slots=True)
class DirectRechargeSummary:
    operation_id: UUID
    status: DirectRechargeStatus
    number: int
    product: DirectRechargeProductReference
    payout: DirectRechargePayout
    total: Money
    requested_at: datetime
    has_partial_refund: bool
    external_reference: str | None = dataclass_field(default=None, repr=False)
    completed_at: datetime | None = None
    raw_status: str | None = dataclass_field(default=None, repr=False)

    @classmethod
    def from_json(cls, data: object) -> "DirectRechargeSummary":
        value = object_data(data)
        if any(
            key not in value or value[key] is None
            for key in (
                "operationId",
                "status",
                "number",
                "product",
                "payout",
                "total",
                "requestedAt",
                "hasPartialRefund",
            )
        ):
            raise ValueError("DirectRechargeSummary is missing a required member.")
        return cls(
            identifier(field(value, "operationId")),
            lenient_enum(DirectRechargeStatus, field(value, "status"), DirectRechargeStatus.UNKNOWN),
            integer(field(value, "number")),
            DirectRechargeProductReference.from_json(field(value, "product")),
            DirectRechargePayout.from_json(field(value, "payout")),
            Money.from_json(field(value, "total")),
            cast(datetime, timestamp(field(value, "requestedAt"))),
            boolean(field(value, "hasPartialRefund")),
            text(field(value, "externalReference")),
            timestamp(field(value, "completedAt")),
            text(field(value, "status")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        result.pop("rawStatus", None)
        if self.raw_status is not None:
            result["status"] = self.raw_status
        return result


@dataclass(frozen=True, slots=True)
class DirectRechargesQuery:
    status: DirectRechargeStatus | None = None
    product_id: UUID | None = None
    from_: datetime | None = None
    to: datetime | None = None
    cursor: str | None = None
    page_size: int | None = None
    raw_status: str | None = dataclass_field(default=None, repr=False)

    @classmethod
    def from_json(cls, data: object) -> "DirectRechargesQuery":
        value = object_data(data)
        return cls(
            lenient_enum(DirectRechargeStatus, field(value, "status"), DirectRechargeStatus.UNKNOWN)
            if field(value, "status") is not None
            else None,
            identifier(field(value, "productId"), optional=True),
            timestamp(field(value, "from")),
            timestamp(field(value, "to")),
            text(field(value, "cursor")),
            integer(field(value, "pageSize")) if field(value, "pageSize") is not None else None,
            text(field(value, "status")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        result.pop("rawStatus", None)
        if self.raw_status is not None:
            result["status"] = self.raw_status
        result.pop("from_", None)
        if self.from_ is not None:
            result["from"] = wire_value(self.from_)
        return result


@dataclass(frozen=True, slots=True)
class DirectRechargeAccepted:
    """Represent only the three members of an unresolved processing response."""

    operation_id: UUID
    operation_type: str = "directRecharge"
    status: str = "processing"

    def __post_init__(self) -> None:
        if self.operation_type != "directRecharge" or self.status != "processing":
            raise ValueError("Invalid processing operation type or status.")

    @classmethod
    def from_json(cls, data: object) -> "DirectRechargeAccepted":
        value = object_data(data)
        if set(value) != {"operationId", "operationType", "status"} or value["operationId"] is None:
            raise ValueError("Processing requires exactly operationId, operationType and status.")
        return cls(identifier(value["operationId"]), text(value["operationType"]) or "", text(value["status"]) or "")

    def to_json(self) -> dict[str, object]:
        return {
            "operationId": str(self.operation_id),
            "operationType": self.operation_type,
            "status": self.status,
        }
