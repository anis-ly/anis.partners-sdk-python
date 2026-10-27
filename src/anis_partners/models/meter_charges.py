"""Immutable meter charges wire models."""

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime
from enum import StrEnum, auto
from typing import cast
from uuid import UUID

from anis_partners.models._json import (
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
from anis_partners.models.money import Money


class MeterChargeStatus(StrEnum):
    UNKNOWN = "unknown"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class MeterRefundStatus(StrEnum):
    UNKNOWN = "unknown"
    REFUNDED = "refunded"
    NOT_CHARGED = "notCharged"
    PENDING = "pending"


class MeterFailureCode(StrEnum):
    UNKNOWN = "unknown"
    METER_NUMBER_INVALID = "meter_number_invalid"
    METER_NOT_WHITELISTED = "meter_not_whitelisted"
    METER_NOT_LINKED = "meter_not_linked"
    METER_REMOVED = "meter_removed"
    METER_INACTIVE = "meter_inactive"
    METER_ACCOUNT_BLOCKED = "meter_account_blocked"
    METER_DATA_INCOMPLETE = "meter_data_incomplete"
    METER_DEBT_EXCEEDS_PACKAGE = "meter_debt_exceeds_package"
    PACKAGE_UNAVAILABLE = "package_unavailable"
    PACKAGE_LIMIT_REACHED = "package_limit_reached"
    TOKEN_NOT_WRITTEN = auto()
    INSUFFICIENT_BALANCE = "insufficient_balance"
    GECOL_UNAVAILABLE = "gecol_unavailable"
    CHARGE_FAILED = "charge_failed"


@dataclass(frozen=True, slots=True)
class MeterPackage:
    id: UUID
    name: str
    gecol_package_name: str
    logo: str | None
    unit_price: Money
    personal_price: Money
    business_price: Money | None = None

    @classmethod
    def from_json(cls, data: object) -> "MeterPackage":
        value = object_data(data)
        if any(
            key not in value or value[key] is None
            for key in ("id", "name", "gecolPackageName", "unitPrice", "personalPrice")
        ):
            raise ValueError("MeterPackage is missing a required member.")
        return cls(
            identifier(field(value, "id")),
            text(field(value, "name"), "") or "",
            text(field(value, "gecolPackageName"), "") or "",
            text(field(value, "logo")),
            Money.from_json(field(value, "unitPrice")),
            Money.from_json(field(value, "personalPrice")),
            Money.from_json(field(value, "businessPrice")) if field(value, "businessPrice") is not None else None,
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        return result


@dataclass(frozen=True, slots=True)
class MeterChargePackage:
    id: UUID
    name: str
    gecol_package_name: str

    @classmethod
    def from_json(cls, data: object) -> "MeterChargePackage":
        value = object_data(data)
        if any(key not in value or value[key] is None for key in ("id", "name", "gecolPackageName")):
            raise ValueError("MeterChargePackage is missing a required member.")
        return cls(
            identifier(field(value, "id")),
            text(field(value, "name"), "") or "",
            text(field(value, "gecolPackageName"), "") or "",
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        return result


@dataclass(frozen=True, slots=True)
class CreateMeterChargeRequest:
    package_id: UUID
    meter_number: str = dataclass_field(repr=False)
    expected_total: Money
    external_reference: str | None = dataclass_field(default=None, repr=False)

    @classmethod
    def from_json(cls, data: object) -> "CreateMeterChargeRequest":
        value = object_data(data)
        if any(key not in value or value[key] is None for key in ("packageId", "meterNumber", "expectedTotal")):
            raise ValueError("CreateMeterChargeRequest is missing a required member.")
        return cls(
            identifier(field(value, "packageId")),
            text(field(value, "meterNumber"), "") or "",
            Money.from_json(field(value, "expectedTotal")),
            text(field(value, "externalReference")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        return result


@dataclass(frozen=True, slots=True)
class MeterToken:
    sequence: int
    label: str
    code: str = dataclass_field(repr=False)
    description: str | None = None

    @classmethod
    def from_json(cls, data: object) -> "MeterToken":
        value = object_data(data)
        if any(key not in value or value[key] is None for key in ("sequence", "label", "code")):
            raise ValueError("MeterToken is missing a required member.")
        return cls(
            integer(field(value, "sequence")),
            text(field(value, "label"), "") or "",
            text(field(value, "code"), "") or "",
            text(field(value, "description")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        return result


@dataclass(frozen=True, slots=True)
class MeterTax:
    description: str
    amount: str

    @classmethod
    def from_json(cls, data: object) -> "MeterTax":
        value = object_data(data)
        if any(key not in value or value[key] is None for key in ("description", "amount")):
            raise ValueError("MeterTax is missing a required member.")
        return cls(
            text(field(value, "description"), "") or "",
            text(field(value, "amount"), "") or "",
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        return result


@dataclass(frozen=True, slots=True)
class MeterReceipt:
    receipt_number: str | None
    credited_amount: str | None
    tokens: tuple[MeterToken, ...] = dataclass_field(repr=False)
    taxes: tuple[MeterTax, ...]

    @classmethod
    def from_json(cls, data: object) -> "MeterReceipt":
        value = object_data(data)
        if any(key not in value or value[key] is None for key in ("tokens", "taxes")):
            raise ValueError("MeterReceipt is missing a required member.")
        tokens = field(value, "tokens")
        if not isinstance(tokens, list):
            raise ValueError("tokens must be a JSON array.")
        taxes = field(value, "taxes")
        if not isinstance(taxes, list):
            raise ValueError("taxes must be a JSON array.")
        return cls(
            text(field(value, "receiptNumber")),
            text(field(value, "creditedAmount")),
            tuple(MeterToken.from_json(item) for item in tokens),
            tuple(MeterTax.from_json(item) for item in taxes),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        return result


@dataclass(frozen=True, slots=True)
class MeterFailure:
    code: MeterFailureCode = dataclass_field(repr=False)
    message: LocalizedText | None = None
    raw_code: str | None = dataclass_field(default=None, repr=False)

    @classmethod
    def from_json(cls, data: object) -> "MeterFailure":
        value = object_data(data)
        if any(key not in value or value[key] is None for key in ("code",)):
            raise ValueError("MeterFailure is missing a required member.")
        return cls(
            lenient_enum(MeterFailureCode, field(value, "code"), MeterFailureCode.UNKNOWN),
            LocalizedText.from_json(field(value, "message")) if field(value, "message") is not None else None,
            text(field(value, "code")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        result.pop("rawCode", None)
        if self.raw_code is not None:
            result["code"] = self.raw_code
        return result


@dataclass(frozen=True, slots=True)
class MeterRefund:
    status: MeterRefundStatus
    amount: Money | None = None
    raw_status: str | None = dataclass_field(default=None, repr=False)

    @classmethod
    def from_json(cls, data: object) -> "MeterRefund":
        value = object_data(data)
        if any(key not in value or value[key] is None for key in ("status",)):
            raise ValueError("MeterRefund is missing a required member.")
        return cls(
            lenient_enum(MeterRefundStatus, field(value, "status"), MeterRefundStatus.UNKNOWN),
            Money.from_json(field(value, "amount")) if field(value, "amount") is not None else None,
            text(field(value, "status")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        result.pop("rawStatus", None)
        if self.raw_status is not None:
            result["status"] = self.raw_status
        return result


@dataclass(frozen=True, slots=True)
class MeterCharge:
    operation_id: UUID
    status: MeterChargeStatus
    wallet_id: UUID
    meter_number: str = dataclass_field(repr=False)
    package: MeterChargePackage
    total: Money
    created_at: datetime
    personal_price: Money
    external_reference: str | None = dataclass_field(default=None, repr=False)
    completed_at: datetime | None = None
    receipt: MeterReceipt | None = dataclass_field(default=None, repr=False)
    failure: MeterFailure | None = dataclass_field(default=None, repr=False)
    refund: MeterRefund | None = None
    raw_status: str | None = dataclass_field(default=None, repr=False)

    @classmethod
    def from_json(cls, data: object) -> "MeterCharge":
        value = object_data(data)
        if any(
            key not in value or value[key] is None
            for key in (
                "operationId",
                "status",
                "walletId",
                "meterNumber",
                "package",
                "total",
                "createdAt",
                "personalPrice",
            )
        ):
            raise ValueError("MeterCharge is missing a required member.")
        return cls(
            identifier(field(value, "operationId")),
            lenient_enum(MeterChargeStatus, field(value, "status"), MeterChargeStatus.UNKNOWN),
            identifier(field(value, "walletId")),
            text(field(value, "meterNumber"), "") or "",
            MeterChargePackage.from_json(field(value, "package")),
            Money.from_json(field(value, "total")),
            cast(datetime, timestamp(field(value, "createdAt"))),
            Money.from_json(field(value, "personalPrice")),
            text(field(value, "externalReference")),
            timestamp(field(value, "completedAt")),
            MeterReceipt.from_json(field(value, "receipt")) if field(value, "receipt") is not None else None,
            MeterFailure.from_json(field(value, "failure")) if field(value, "failure") is not None else None,
            MeterRefund.from_json(field(value, "refund")) if field(value, "refund") is not None else None,
            text(field(value, "status")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        result.pop("rawStatus", None)
        if self.raw_status is not None:
            result["status"] = self.raw_status
        return result


@dataclass(frozen=True, slots=True)
class MeterChargeSummary:
    operation_id: UUID
    status: MeterChargeStatus
    meter_number: str = dataclass_field(repr=False)
    package: MeterChargePackage
    total: Money
    created_at: datetime
    external_reference: str | None = dataclass_field(default=None, repr=False)
    completed_at: datetime | None = None
    raw_status: str | None = dataclass_field(default=None, repr=False)

    @classmethod
    def from_json(cls, data: object) -> "MeterChargeSummary":
        value = object_data(data)
        if any(
            key not in value or value[key] is None
            for key in ("operationId", "status", "meterNumber", "package", "total", "createdAt")
        ):
            raise ValueError("MeterChargeSummary is missing a required member.")
        return cls(
            identifier(field(value, "operationId")),
            lenient_enum(MeterChargeStatus, field(value, "status"), MeterChargeStatus.UNKNOWN),
            text(field(value, "meterNumber"), "") or "",
            MeterChargePackage.from_json(field(value, "package")),
            Money.from_json(field(value, "total")),
            cast(datetime, timestamp(field(value, "createdAt"))),
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
class MeterChargesQuery:
    status: MeterChargeStatus | None = None
    meter_number: str | None = dataclass_field(default=None, repr=False)
    from_: datetime | None = None
    to: datetime | None = None
    cursor: str | None = None
    page_size: int | None = None
    raw_status: str | None = dataclass_field(default=None, repr=False)

    @classmethod
    def from_json(cls, data: object) -> "MeterChargesQuery":
        value = object_data(data)
        return cls(
            lenient_enum(MeterChargeStatus, field(value, "status"), MeterChargeStatus.UNKNOWN)
            if field(value, "status") is not None
            else None,
            text(field(value, "meterNumber")),
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
class MeterChargeAccepted:
    """Represent only the three members of an unresolved processing response."""

    operation_id: UUID
    operation_type: str = "meterCharge"
    status: str = "processing"

    def __post_init__(self) -> None:
        if self.operation_type != "meterCharge" or self.status != "processing":
            raise ValueError("Invalid processing operation type or status.")

    @classmethod
    def from_json(cls, data: object) -> "MeterChargeAccepted":
        value = object_data(data)
        if set(value) != {"operationId", "operationType", "status"} or value["operationId"] is None:
            raise ValueError("Processing requires exactly operationId, operationType and status.")
        return cls(identifier(value["operationId"]), text(value["operationType"]) or "", text(value["status"]) or "")

    def to_json(self) -> dict[str, object]:
        return model_json(self)
