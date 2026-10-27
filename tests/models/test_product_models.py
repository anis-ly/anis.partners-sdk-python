"""Pin full product reads, summaries, processing DTOs and required webhook nulls."""

from dataclasses import fields
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

import anis_partners as sdk
from anis_partners import (
    DirectRecharge,
    DirectRechargeAccepted,
    DirectRechargeAmountIn,
    DirectRechargeProduct,
    DirectRechargeRecipientField,
    DirectRechargeStatus,
    DirectRechargeSummary,
    MeterCharge,
    MeterChargeAccepted,
    MeterChargeSummary,
    MeterFailure,
    MeterFailureCode,
    WebhookEndpoint,
    WebhookEnvelope,
    WebhookEvent,
    WebhookEventType,
)
from tests.support.products import FIXTURES, accepted, fixture, full_read, meter_request, recharge_request


@pytest.mark.parametrize(
    "path", sorted(p for p in FIXTURES.glob("*.json") if p.stem != "sources"), ids=lambda p: p.stem
)
def test_shared_public_reads_and_summaries_round_trip(path: Path) -> None:
    data = fixture(path.stem)
    if path.stem.startswith("get-"):
        model = MeterChargeSummary if "meter" in path.stem else DirectRechargeSummary
        for item in data["items"]:
            assert model.from_json(item).to_json() == item
    else:
        read_model = MeterCharge if path.stem.startswith("meter") else DirectRecharge
        assert read_model.from_json(data).to_json() == data


@pytest.mark.parametrize(("model", "meter"), [(MeterChargeAccepted, True), (DirectRechargeAccepted, False)])
def test_processing_body_has_exactly_three_members(model: Any, meter: bool) -> None:
    data = accepted(meter)
    assert model.from_json(data).to_json() == data
    assert {item.name for item in fields(model)} == {"operation_id", "operation_type", "status"}
    for bad in (
        {**data, "total": {}},
        {**data, "operationType": "other"},
        {key: val for key, val in data.items() if key != "operationType"},
        {**data, "status": "completed"},
        {**data, "operationId": None},
    ):
        with pytest.raises(ValueError, match=r"required|Processing|Invalid|Payout|text model"):
            model.from_json(bad)


@pytest.mark.parametrize(("model", "meter"), [(MeterCharge, True), (DirectRecharge, False)])
def test_processing_is_not_a_full_read(model: Any, meter: bool) -> None:
    with pytest.raises(ValueError, match=r"required|Processing|Invalid|Payout|text model"):
        model.from_json(accepted(meter))
    data = full_read(meter)
    required = (
        ["operationId", "walletId", "total", "createdAt", "personalPrice"]
        if meter
        else ["operationId", "walletId", "requestedAt", "payout", "number"]
    )
    for key in required:
        with pytest.raises(ValueError, match=r"required|Processing|Invalid|Payout|text model"):
            model.from_json({name: value for name, value in data.items() if name != key})


@pytest.mark.parametrize(
    "code", [member.value for member in MeterFailureCode if member is not MeterFailureCode.UNKNOWN] + ["future_failure"]
)
def test_meter_failure_values_retain_the_raw_code(code: str) -> None:
    data = {"code": code, "message": {"ar": "رفض"}}
    failure = MeterFailure.from_json(data)
    assert failure.to_json() == data
    assert failure.raw_code == code
    assert len(MeterFailureCode) == 15
    if code == "future_failure":
        assert failure.code is MeterFailureCode.UNKNOWN


def test_future_status_and_dotted_event_type_are_retained() -> None:
    data = full_read(False, "futureState")
    model = DirectRecharge.from_json(data)
    assert model.status is DirectRechargeStatus.UNKNOWN
    assert model.raw_status == "futureState"
    assert model.to_json() == data
    envelope = {
        "id": data["operationId"],
        "type": "future.event",
        "occurredAt": data["requestedAt"],
        "applicationId": data["walletId"],
        "data": {"future": "sentinel"},
    }
    parsed = WebhookEnvelope.from_json(envelope)
    assert parsed.type is WebhookEventType.UNKNOWN
    assert parsed.raw_type == "future.event"
    assert parsed.to_json() == envelope
    assert "sentinel" not in repr(parsed)


def test_suspended_type_current_in_progress_data_is_accepted() -> None:
    data = fixture("circle-suspended-after-recipient-fix")
    envelope = {
        "id": data["operationId"],
        "type": "directRecharge.suspended",
        "occurredAt": data["requestedAt"],
        "applicationId": data["walletId"],
        "data": data,
    }
    parsed = WebhookEnvelope.from_json(envelope)
    assert isinstance(parsed.data, DirectRecharge)
    assert parsed.data.status is DirectRechargeStatus.IN_PROGRESS
    assert parsed.to_json() == envelope


def test_recipient_field_uses_the_for_wire_member() -> None:
    data = {
        "key": "recipient_number",
        "name": {"ar": "رقم"},
        "kind": "text",
        "for": "recipient",
        "order": 1,
        "validation": "^01[0-9]{9}$",
        "validationMessage": {"en": "Invalid number"},
    }
    model = DirectRechargeRecipientField.from_json(data)
    assert model.for_.value == "recipient"
    assert model.to_json() == data
    assert "for_" not in model.to_json()
    assert "Invalid number" not in repr(model)


def test_unavailable_product_does_not_invent_limits() -> None:
    data = {
        "id": str(UUID(int=1)),
        "title": "عنوان",
        "type": "external",
        "available": False,
        "payoutCurrency": {"name": "جنيه مصري"},
        "recipientFields": [],
    }
    model = DirectRechargeProduct.from_json(data)
    assert model.available is False
    assert model.limits is None
    assert model.to_json() == data


@pytest.mark.parametrize("status", ["notConfigured", "pendingVerification", "verified", "disabled", "futureState"])
def test_endpoint_preserves_required_nullable_members(status: str) -> None:
    data = {"url": None, "status": status, "generation": None}
    assert WebhookEndpoint.from_json(data).to_json() == data
    for key in data:
        with pytest.raises(ValueError, match=r"required|Processing|Invalid|Payout|text model"):
            WebhookEndpoint.from_json({name: value for name, value in data.items() if name != key})


def test_event_preserves_required_nullable_members() -> None:
    data = {
        "id": str(UUID(int=1)),
        "type": "directRecharge.completed",
        "status": "pending",
        "attempts": 0,
        "lastAttemptAt": None,
        "nextAttemptAt": None,
        "lastResponseCode": None,
        "lastFailureKind": None,
    }
    assert WebhookEvent.from_json(data).to_json() == data
    for key in data:
        with pytest.raises(ValueError, match=r"required|Processing|Invalid|Payout|text model"):
            WebhookEvent.from_json({name: value for name, value in data.items() if name != key})


def test_request_models_round_trip_and_hide_recipient_data() -> None:
    for model in (meter_request(), recharge_request()):
        assert type(model).from_json(model.to_json()) == model
        assert "operationId" not in model.to_json()
        assert "0268000710262" not in repr(model)
        assert "01012345678" not in repr(model)
        assert "Family support" not in repr(model)
    assert set(recharge_request().to_json()) == {
        "productId",
        "payoutAmount",
        "expectedTotal",
        "recipient",
        "note",
        "externalReference",
    }
    assert (
        not {"price", "priceWithCommission", "extraFee", "customerWhatsappNumber"} & recharge_request().to_json().keys()
    )


@pytest.mark.parametrize("amount", [1.1, 1, "1.0000"])
def test_payout_rejects_numbers_and_excess_scale(amount: object) -> None:
    data = recharge_request().to_json()
    data["payoutAmount"] = amount
    with pytest.raises(ValueError, match=r"required|Processing|Invalid|Payout|text model"):
        sdk.CreateDirectRechargeRequest.from_json(data)


def test_public_models_and_groups_are_exported() -> None:
    for module in (
        sdk.models.meter_charges,
        sdk.models.direct_recharges,
        sdk.models.direct_recharge_products,
        sdk.models.product_results,
        sdk.models.webhooks,
    ):
        for name, value in vars(module).items():
            if getattr(value, "__module__", None) == module.__name__ and not name.startswith("_"):
                assert name in sdk.__all__
                assert name in sdk.models.__all__
                assert getattr(sdk, name) is value
    for prefix in ("Sync", "Async"):
        for name in ("MeterCharge", "DirectRechargeProduct", "DirectRecharge", "WebhookEndpoint", "WebhookEvent"):
            assert prefix + name + "Operations" in sdk.__all__
    assert isinstance(MeterCharge.from_json(full_read()).created_at, datetime)
    assert DirectRechargeAmountIn.FX.value == "fx"


def test_shared_fixture_bytes_match_the_source_hashes() -> None:
    import hashlib

    sources = fixture("sources")
    assert len(sources) == 13
    for source, digest in sources.items():
        parts = source.split("/")
        local = "get-" + parts[-1] if parts[0] == "list-fixtures" else parts[-2] + ".json"
        assert hashlib.sha256((FIXTURES / local).read_bytes()).hexdigest() == digest


def test_empty_pages_preserve_the_terminal_null_cursor() -> None:
    assert sdk.Page().to_json() == {"items": [], "nextCursor": None}


def test_future_delivery_failure_kind_round_trips() -> None:
    data = {
        "id": str(UUID(int=1)),
        "type": "future.event",
        "status": "futureStatus",
        "attempts": 1,
        "lastAttemptAt": None,
        "nextAttemptAt": None,
        "lastResponseCode": None,
        "lastFailureKind": "futureFailure",
    }
    assert WebhookEvent.from_json(data).to_json() == data


def test_product_queries_reject_naive_datetime_without_sending() -> None:
    from anis_partners import MeterChargesQuery, WebhookEventsQuery

    naive = datetime(2026, 10, 20)
    for query in (MeterChargesQuery(from_=naive), WebhookEventsQuery(since=naive)):
        with pytest.raises(ValueError, match="timezone"):
            query.to_json()


def test_recipient_field_preserves_a_future_for_value() -> None:
    data = {"key": "Future", "kind": "text", "for": "futureParty", "order": 1}
    model = DirectRechargeRecipientField.from_json(data)
    assert model.for_.value == "unknown"
    assert model.raw_for_ == "futureParty"
    assert model.name is None
    assert model.to_json() == data


def test_processing_location_is_separate_from_acknowledgement_body() -> None:
    from datetime import timedelta

    from anis_partners import DirectRechargeProcessing
    from tests.support.partner import OPERATION

    data = accepted(False)
    location = f"/v1/direct-recharges/{OPERATION}"
    acknowledgement = DirectRechargeAccepted(OPERATION)
    processing = DirectRechargeProcessing(acknowledgement, timedelta(seconds=5), location)
    assert processing.location == location
    assert processing.recharge is acknowledgement
    assert acknowledgement.to_json() == data
    assert set(acknowledgement.to_json()) == {"operationId", "operationType", "status"}
    assert {item.name for item in fields(acknowledgement)} == {"operation_id", "operation_type", "status"}
    with pytest.raises(ValueError, match="exactly"):
        DirectRechargeAccepted.from_json({**data, "location": location})
