"""Immutable webhooks wire models."""

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime
from enum import StrEnum
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
from anis_partners.models.direct_recharges import DirectRecharge
from anis_partners.models.meter_charges import MeterCharge


class WebhookEndpointStatus(StrEnum):
    UNKNOWN = "unknown"
    NOT_CONFIGURED = "notConfigured"
    PENDING_VERIFICATION = "pendingVerification"
    VERIFIED = "verified"
    DISABLED = "disabled"


class WebhookEventType(StrEnum):
    UNKNOWN = "unknown"
    METER_CHARGE_SUCCEEDED = "meterCharge.succeeded"
    METER_CHARGE_FAILED = "meterCharge.failed"
    DIRECT_RECHARGE_PAID = "directRecharge.paid"
    DIRECT_RECHARGE_PAYMENT_FAILED = "directRecharge.paymentFailed"
    DIRECT_RECHARGE_SUSPENDED = "directRecharge.suspended"
    DIRECT_RECHARGE_COMPLETED = "directRecharge.completed"
    DIRECT_RECHARGE_REJECTED = "directRecharge.rejected"
    DIRECT_RECHARGE_PARTIALLY_REFUNDED = "directRecharge.partiallyRefunded"
    WEBHOOK_ENDPOINT_VERIFICATION = "webhook_endpoint.verification"
    WEBHOOK_ENDPOINT_TEST = "webhook_endpoint.test"


class WebhookDeliveryStatus(StrEnum):
    UNKNOWN = "unknown"
    PENDING = "pending"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    RETRYING = "retrying"
    FAILED = "failed"
    WAITING_FOR_PROJECTION = "waitingForProjection"
    WAITING_FOR_ENDPOINT = "waitingForEndpoint"
    CANCELLED = "cancelled"


class WebhookFailureKind(StrEnum):
    UNKNOWN = "unknown"
    HTTP_STATUS = "httpStatus"
    TIMEOUT = "timeout"
    CONNECT = "connect"
    TLS = "tls"
    TARGET_REFUSED = "targetRefused"
    RESPONSE_TOO_LARGE = "responseTooLarge"
    CHALLENGE_MISMATCH = "challengeMismatch"
    PROJECTION_UNAVAILABLE = "projectionUnavailable"
    ENDPOINT_DISABLED = "endpointDisabled"
    SIGNING_UNAVAILABLE = "signingUnavailable"


@dataclass(frozen=True, slots=True)
class SetWebhookEndpointRequest:
    url: str = dataclass_field(repr=False)

    @classmethod
    def from_json(cls, data: object) -> "SetWebhookEndpointRequest":
        value = object_data(data)
        if any(key not in value or value[key] is None for key in ("url",)):
            raise ValueError("SetWebhookEndpointRequest is missing a required member.")
        return cls(
            text(field(value, "url"), "") or "",
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        return result


@dataclass(frozen=True, slots=True)
class WebhookEndpoint:
    url: str | None = dataclass_field(repr=False)
    status: WebhookEndpointStatus
    generation: int | None
    raw_status: str | None = dataclass_field(default=None, repr=False)

    @classmethod
    def from_json(cls, data: object) -> "WebhookEndpoint":
        value = object_data(data)
        if any(key not in value for key in ("url", "status", "generation")):
            raise ValueError("WebhookEndpoint is missing a required member.")
        if field(value, "status") is None:
            raise ValueError("Endpoint status is required.")
        return cls(
            text(field(value, "url")),
            lenient_enum(WebhookEndpointStatus, field(value, "status"), WebhookEndpointStatus.UNKNOWN),
            integer(field(value, "generation")) if field(value, "generation") is not None else None,
            text(field(value, "status")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        result.pop("rawStatus", None)
        if self.raw_status is not None:
            result["status"] = self.raw_status
        result["url"] = wire_value(self.url)
        result["generation"] = wire_value(self.generation)
        return result


@dataclass(frozen=True, slots=True)
class WebhookEventAccepted:
    id: UUID
    status: str
    queued_at: datetime
    type: WebhookEventType | None = None
    raw_type: str | None = dataclass_field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.status != "pending":
            raise ValueError("An accepted webhook event must be pending.")

    @classmethod
    def from_json(cls, data: object) -> "WebhookEventAccepted":
        value = object_data(data)
        if any(key not in value or value[key] is None for key in ("id", "status", "queuedAt")):
            raise ValueError("WebhookEventAccepted is missing a required member.")
        return cls(
            identifier(field(value, "id")),
            text(field(value, "status"), "") or "",
            cast(datetime, timestamp(field(value, "queuedAt"))),
            lenient_enum(WebhookEventType, field(value, "type"), WebhookEventType.UNKNOWN)
            if field(value, "type") is not None
            else None,
            text(field(value, "type")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        result.pop("rawType", None)
        if self.raw_type is not None:
            result["type"] = self.raw_type
        return result


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    id: UUID
    type: WebhookEventType
    status: WebhookDeliveryStatus
    attempts: int
    last_attempt_at: datetime | None
    next_attempt_at: datetime | None
    last_response_code: int | None
    last_failure_kind: WebhookFailureKind | None
    raw_type: str | None = dataclass_field(default=None, repr=False)
    raw_status: str | None = dataclass_field(default=None, repr=False)
    raw_last_failure_kind: str | None = dataclass_field(default=None, repr=False)

    @classmethod
    def from_json(cls, data: object) -> "WebhookEvent":
        value = object_data(data)
        if any(
            key not in value
            for key in (
                "id",
                "type",
                "status",
                "attempts",
                "lastAttemptAt",
                "nextAttemptAt",
                "lastResponseCode",
                "lastFailureKind",
            )
        ):
            raise ValueError("WebhookEvent is missing a required member.")
        if any(field(value, key) is None for key in ("id", "type", "status", "attempts")):
            raise ValueError("WebhookEvent is missing a required member.")
        return cls(
            identifier(field(value, "id")),
            lenient_enum(WebhookEventType, field(value, "type"), WebhookEventType.UNKNOWN),
            lenient_enum(WebhookDeliveryStatus, field(value, "status"), WebhookDeliveryStatus.UNKNOWN),
            integer(field(value, "attempts")),
            timestamp(field(value, "lastAttemptAt")),
            timestamp(field(value, "nextAttemptAt")),
            integer(field(value, "lastResponseCode")) if field(value, "lastResponseCode") is not None else None,
            lenient_enum(WebhookFailureKind, field(value, "lastFailureKind"), WebhookFailureKind.UNKNOWN)
            if field(value, "lastFailureKind") is not None
            else None,
            text(field(value, "type")),
            text(field(value, "status")),
            text(field(value, "lastFailureKind")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        result.pop("rawType", None)
        if self.raw_type is not None:
            result["type"] = self.raw_type
        result.pop("rawStatus", None)
        if self.raw_status is not None:
            result["status"] = self.raw_status
        result.pop("rawLastFailureKind", None)
        if self.raw_last_failure_kind is not None:
            result["lastFailureKind"] = self.raw_last_failure_kind
        result["lastAttemptAt"] = wire_value(self.last_attempt_at)
        result["nextAttemptAt"] = wire_value(self.next_attempt_at)
        result["lastResponseCode"] = wire_value(self.last_response_code)
        result["lastFailureKind"] = (
            self.raw_last_failure_kind if self.raw_last_failure_kind is not None else wire_value(self.last_failure_kind)
        )
        return result


@dataclass(frozen=True, slots=True)
class WebhookEventsQuery:
    status: WebhookDeliveryStatus | None = None
    since: datetime | None = None
    cursor: str | None = None
    raw_status: str | None = dataclass_field(default=None, repr=False)

    @classmethod
    def from_json(cls, data: object) -> "WebhookEventsQuery":
        value = object_data(data)
        return cls(
            lenient_enum(WebhookDeliveryStatus, field(value, "status"), WebhookDeliveryStatus.UNKNOWN)
            if field(value, "status") is not None
            else None,
            timestamp(field(value, "since")),
            text(field(value, "cursor")),
            text(field(value, "status")),
        )

    def to_json(self) -> dict[str, object]:
        result = model_json(self)
        result.pop("rawStatus", None)
        if self.raw_status is not None:
            result["status"] = self.raw_status
        return result


@dataclass(frozen=True, slots=True)
class WebhookEnvelope:
    """Decode event data after the caller has verified the delivery's raw bytes."""

    id: UUID
    type: WebhookEventType
    occurred_at: datetime
    application_id: UUID
    data: MeterCharge | DirectRecharge | Mapping[str, object] = dataclass_field(repr=False)
    raw_type: str | None = dataclass_field(default=None, repr=False)

    @classmethod
    def from_json(cls, data: object) -> "WebhookEnvelope":
        value = object_data(data)
        if any(field(value, key) is None for key in ("id", "type", "occurredAt", "applicationId", "data")):
            raise ValueError("WebhookEnvelope is missing a required member.")
        raw_type = text(field(value, "type"))
        kind = lenient_enum(WebhookEventType, raw_type, WebhookEventType.UNKNOWN)
        body = object_data(field(value, "data"))
        parsed: MeterCharge | DirectRecharge | Mapping[str, object] = body
        if kind in {WebhookEventType.METER_CHARGE_SUCCEEDED, WebhookEventType.METER_CHARGE_FAILED}:
            parsed = MeterCharge.from_json(body)
        elif kind in {
            WebhookEventType.DIRECT_RECHARGE_PAID,
            WebhookEventType.DIRECT_RECHARGE_PAYMENT_FAILED,
            WebhookEventType.DIRECT_RECHARGE_SUSPENDED,
            WebhookEventType.DIRECT_RECHARGE_COMPLETED,
            WebhookEventType.DIRECT_RECHARGE_REJECTED,
            WebhookEventType.DIRECT_RECHARGE_PARTIALLY_REFUNDED,
        }:
            parsed = DirectRecharge.from_json(body)
        return cls(
            identifier(value["id"]),
            kind,
            cast(datetime, timestamp(value["occurredAt"])),
            identifier(value["applicationId"]),
            parsed,
            raw_type,
        )

    def to_json(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "type": self.raw_type or self.type.value,
            "occurredAt": wire_value(self.occurred_at),
            "applicationId": str(self.application_id),
            "data": wire_value(self.data),
        }
