"""Exercise product creates and recovery through real request and response signatures."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import pytest

from anis_partners import (
    AnisApiError,
    DirectRechargeNotPlaced,
    DirectRechargeOutcomeUnknown,
    DirectRechargeProcessing,
    MalformedResponseError,
    MeterChargeAccepted,
    MeterChargeFinal,
    MeterChargeNotPlaced,
    MeterChargeOutcomeUnknown,
    MeterChargeProcessing,
    MeterChargesQuery,
    MeterChargeStatus,
    MeterRefundStatus,
    RequestSigningError,
)
from tests.operations.test_signed_wire_capture import _wire_signature_verifies
from tests.support.partner import OPERATION, WALLET
from tests.support.products import (
    CURSOR,
    NOW,
    accepted,
    answer,
    api_requests,
    collected,
    fixture,
    full_read,
    meter_request,
    problem,
    product_client,
    recharge_request,
    resolved,
)
from tests.support.sdk_wire import SignedMockWire, WireAnswer

pytestmark = pytest.mark.anyio


def _group(client: Any, meter: bool) -> Any:
    return client.meter_charges if meter else client.direct_recharges


def _request(meter: bool) -> Any:
    return meter_request() if meter else recharge_request()


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("meter", [True, False], ids=["meter", "direct-recharge"])
async def test_meter_resume_keeps_the_original_operation_id(mode: str, meter: bool) -> None:
    count = 0

    def respond(request: httpx.Request) -> WireAnswer:
        nonlocal count
        count += 1
        if count == 1:
            raise httpx.ReadTimeout("No answer")
        return answer(
            accepted(meter),
            202,
            {"Location": f"/v1/{'meter-charges' if meter else 'direct-recharges'}/{OPERATION}", "Retry-After": "7"},
        )

    wire = SignedMockWire(respond)
    async with product_client(mode, wire) as client:
        group = _group(client, meter)
        request = _request(meter)
        unknown = await resolved(group.create(wallet_id=WALLET, operation_id=OPERATION, request=request))
        assert isinstance(unknown, (MeterChargeOutcomeUnknown, DirectRechargeOutcomeUnknown))
        result = await resolved(group.resume(wallet_id=WALLET, operation_id=OPERATION, request=request))
        assert isinstance(result, (MeterChargeProcessing, DirectRechargeProcessing))
        assert result.operation_id == OPERATION
        assert result.retry_after == timedelta(seconds=7)
        assert result.location is not None
        assert result.location.endswith(str(OPERATION))
    sent = api_requests(wire)
    assert len(sent) == 2
    assert sent[0].content == sent[1].content
    assert all(item.headers["Idempotency-Key"] == str(OPERATION) for item in sent)
    assert sent[0].headers["Nonce"] != sent[1].headers["Nonce"]
    for item in sent:
        _wire_signature_verifies(item)
    assert b'"operationId"' not in sent[0].content
    if meter:
        assert b'"meterNumber":"0268000710262"' in sent[0].content


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("meter", [True, False])
@pytest.mark.parametrize(
    "kind",
    [
        "empty",
        "null",
        "unreadable",
        "wrong-id",
        "extra-202",
        "wrong-type",
        "missing-type",
        "unknown-status",
        "wrong-status",
    ],
)
async def test_unusable_create_answers_preserve_unknown_outcome(mode: str, meter: bool, kind: str) -> None:
    data = accepted(meter)
    status = 202
    if kind == "wrong-id":
        data["operationId"] = str(uuid4())
    if kind == "extra-202":
        data["walletId"] = str(WALLET)
    if kind == "wrong-type":
        data["operationType"] = "order"
    if kind == "missing-type":
        data.pop("operationType")
    if kind == "unknown-status":
        data, status = full_read(meter, "futureState"), 200
    if kind == "wrong-status":
        status = 201
    reply = answer(data, status)
    if kind in {"empty", "null", "unreadable"}:
        reply = WireAnswer(202, {"empty": b"", "null": b"null", "unreadable": b"<html>"}[kind])
    wire = SignedMockWire(lambda request: reply)
    async with product_client(mode, wire) as client:
        result = await resolved(
            _group(client, meter).create(wallet_id=WALLET, operation_id=OPERATION, request=_request(meter))
        )
        assert isinstance(result, (MeterChargeOutcomeUnknown, DirectRechargeOutcomeUnknown))
        assert result.operation_id == OPERATION
        assert result.suggested_delay == timedelta(seconds=5)


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("meter", [True, False])
@pytest.mark.parametrize("signing", ["missing", "bad-digest", "keys-unavailable"])
async def test_unverified_create_answers_are_unknown(mode: str, meter: bool, signing: Any) -> None:
    headers = {"Content-Digest": "sha-256=:AAAA:"} if signing == "bad-digest" else None
    wire = SignedMockWire(
        lambda request: answer(accepted(meter), 202, headers), signing="never" if signing == "missing" else "gateway"
    )
    if signing == "keys-unavailable":
        original = wire.handle

        def handler(request: httpx.Request) -> Any:
            if request.url.path.startswith("/.well-known/"):
                raise httpx.ConnectError("Key document unavailable")
            return original(request)

        wire.transport = httpx.MockTransport(handler)
    async with product_client(mode, wire) as client:
        result = await resolved(
            _group(client, meter).create(wallet_id=WALLET, operation_id=OPERATION, request=_request(meter))
        )
        assert isinstance(result, (MeterChargeOutcomeUnknown, DirectRechargeOutcomeUnknown))
        assert result.operation_id == OPERATION


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    ("meter", "code", "status"),
    [
        (True, "meter_rejected", 422),
        (True, "package_unavailable", 409),
        (False, "direct_recharge_product_unavailable", 409),
        (False, "amount_out_of_range", 422),
        (True, "price_changed", 409),
        (False, "insufficient_balance", 409),
        (False, "purchase_not_allowed", 403),
        (True, "spending_limit_exceeded", 429),
        (False, "validation_failed", 422),
    ],
)
async def test_definitive_create_and_recorded_resume_refusals(mode: str, meter: bool, code: str, status: Any) -> None:
    headers: dict[str, str] = {}
    wire = SignedMockWire(lambda request: problem(code, status, headers))
    async with product_client(mode, wire) as client:
        group = _group(client, meter)
        result = await resolved(group.create(wallet_id=WALLET, operation_id=OPERATION, request=_request(meter)))
        assert isinstance(result, (MeterChargeNotPlaced, DirectRechargeNotPlaced))
        assert isinstance(result.refusal, AnisApiError)
        assert result.refusal.status == status
        result = await resolved(group.resume(wallet_id=WALLET, operation_id=OPERATION, request=_request(meter)))
        assert isinstance(result, (MeterChargeOutcomeUnknown, DirectRechargeOutcomeUnknown))
        headers["Idempotency-Replayed"] = "true"
        result = await resolved(group.resume(wallet_id=WALLET, operation_id=OPERATION, request=_request(meter)))
        assert isinstance(result, (MeterChargeNotPlaced, DirectRechargeNotPlaced))
        assert isinstance(result.refusal, AnisApiError)
        assert result.refusal.raw_code == code


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("meter", [True, False])
@pytest.mark.parametrize("age", [59, 60, 61])
async def test_sdk_maps_simulated_59_60_61_second_gateway_responses(mode: str, meter: bool, age: int) -> None:
    wire = SignedMockWire(
        lambda request: answer(accepted(meter), 202) if age < 60 else problem("idempotency_conflict", 409)
    )
    async with product_client(mode, wire) as client:
        result = await resolved(
            _group(client, meter).resume(wallet_id=WALLET, operation_id=OPERATION, request=_request(meter))
        )
        if age < 60:
            assert isinstance(result, (MeterChargeProcessing, DirectRechargeProcessing))
        else:
            assert isinstance(result, (MeterChargeOutcomeUnknown, DirectRechargeOutcomeUnknown))
            assert isinstance(result.cause, AnisApiError)
            assert result.cause.raw_code == "idempotency_conflict"
        assert result.operation_id == OPERATION
    assert len(api_requests(wire)) == 1
    assert api_requests(wire)[0].headers["Idempotency-Key"] == str(OPERATION)


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("meter", [True, False])
@pytest.mark.parametrize(
    ("code", "status", "delay"),
    [
        ("invalid_credentials", 401, 60),
        ("insufficient_scope", 403, 60),
        ("wallet_not_granted", 404, 60),
        ("malformed_signed_request", 400, 60),
        ("dependency_unavailable", 503, 5),
        ("internal_error", 500, 5),
        ("new_code", 409, 5),
    ],
)
async def test_access_and_uncertain_refusals_stay_unknown(
    mode: str, meter: bool, code: str, status: Any, delay: Any
) -> None:
    wire = SignedMockWire(lambda request: problem(code, status))
    async with product_client(mode, wire) as client:
        result = await resolved(
            _group(client, meter).resume(wallet_id=WALLET, operation_id=OPERATION, request=_request(meter))
        )
        assert isinstance(result, (MeterChargeOutcomeUnknown, DirectRechargeOutcomeUnknown))
        assert result.suggested_delay == timedelta(seconds=delay)


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("meter", [True, False])
async def test_resume_preserves_zero_retry_after_and_changed_intent_is_not_retried(mode: str, meter: bool) -> None:
    wire = SignedMockWire(lambda request: problem("invalid_credentials", 401, {"Retry-After": "0"}))
    async with product_client(mode, wire) as client:
        result = await resolved(
            _group(client, meter).resume(wallet_id=WALLET, operation_id=OPERATION, request=_request(meter))
        )
        assert result.suggested_delay == timedelta(0)
        wire.answer = lambda request: problem("idempotency_conflict", 409)
        changed = replace(_request(meter), external_reference="different-intent")
        result = await resolved(_group(client, meter).resume(wallet_id=WALLET, operation_id=OPERATION, request=changed))
        assert isinstance(result, (MeterChargeOutcomeUnknown, DirectRechargeOutcomeUnknown))
    assert len(api_requests(wire)) == 2
    assert api_requests(wire)[0].content != api_requests(wire)[1].content


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("meter", [True, False])
async def test_signer_failure_is_preserved_before_send(mode: str, meter: bool) -> None:
    wire = SignedMockWire()
    async with product_client(mode, wire) as client:
        client._core.closed = True
        with pytest.raises(RequestSigningError):
            await resolved(
                _group(client, meter).create(wallet_id=WALLET, operation_id=OPERATION, request=_request(meter))
            )
    assert not wire.requests


@pytest.mark.parametrize("meter", [True, False])
async def test_async_product_cancellation_is_preserved(meter: bool) -> None:
    async def handler(request: httpx.Request) -> Any:
        raise asyncio.CancelledError

    wire = SignedMockWire()
    wire.transport = httpx.MockTransport(handler)
    async with product_client("async", wire) as client:
        with pytest.raises(asyncio.CancelledError):
            await _group(client, meter).create(wallet_id=WALLET, operation_id=OPERATION, request=_request(meter))


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    ("status", "refund", "final"),
    [
        ("processing", None, False),
        ("succeeded", None, True),
        ("failed", "refunded", True),
        ("failed", "notCharged", True),
        ("failed", "pending", False),
    ],
)
async def test_meter_full_reads_keep_refund_finality(mode: str, status: Any, refund: Any, final: bool) -> None:
    data = full_read(status=status)
    if status != "succeeded":
        data.pop("receipt", None)
        data.pop("completedAt", None)
    if refund:
        data["refund"] = {"status": refund}
        data["failure"] = {"code": "charge_failed", "message": {"ar": "رفض"}}
    wire = SignedMockWire(lambda request: answer(data))
    async with product_client(mode, wire) as client:
        read = await resolved(client.meter_charges.get(OPERATION))
        assert read.to_json() == data
        result = await resolved(
            client.meter_charges.resume(wallet_id=WALLET, operation_id=OPERATION, request=meter_request())
        )
        assert isinstance(result, MeterChargeFinal if final else MeterChargeProcessing)
        if status != "succeeded":
            assert read.completed_at is None
        if status == "succeeded":
            assert [token.sequence for token in read.receipt.tokens] == [1, 2, 3]
            assert read.receipt.tokens[0].code == data["receipt"]["tokens"][0]["code"]
            assert read.receipt.taxes[0].amount == data["receipt"]["taxes"][0]["amount"]


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_meter_get_processing_uses_accepted_dto(mode: str) -> None:
    wire = SignedMockWire(lambda request: answer(accepted(), 202))
    async with product_client(mode, wire) as client:
        assert isinstance(await resolved(client.meter_charges.get(OPERATION)), MeterChargeAccepted)
        wire.answer = lambda request: answer({**accepted(), "receipt": {}}, 202)
        with pytest.raises(MalformedResponseError):
            await resolved(client.meter_charges.get(OPERATION))


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_meter_packages_page_omits_business_price(mode: str) -> None:
    package = {
        "id": str(OPERATION),
        "name": "باقة",
        "gecolPackageName": "PKG_100",
        "logo": "https://cdn.test/100.png",
        "unitPrice": {"amount": "97.500", "currency": "LYD"},
        "personalPrice": {"amount": "100.000", "currency": "LYD"},
    }
    wire = SignedMockWire(lambda request: answer({"items": [package], "nextCursor": None}))
    async with product_client(mode, wire) as client:
        page = await resolved(client.meter_charges.get_meter_packages_page(WALLET, CURSOR))
        assert page.items[0].business_price is None
        assert page.items[0].to_json() == package
        assert len(await collected(client.meter_charges.get_meter_packages(WALLET))) == 1
    assert wire.key_document_requests == 0
    assert api_requests(wire)[0].url.params["cursor"] == CURSOR
    assert api_requests(wire)[0].content == b""


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_meter_list_preserves_every_filter_and_cursor(mode: str) -> None:
    data = fixture("get-meter-charges")
    count = 0

    def respond(request: httpx.Request) -> WireAnswer:
        nonlocal count
        count += 1
        return answer({**data, "nextCursor": CURSOR if count == 1 else None})

    wire = SignedMockWire(respond)
    query = MeterChargesQuery(MeterChargeStatus.SUCCEEDED, "0268000710262", NOW, NOW, cursor="initial+/=", page_size=50)
    async with product_client(mode, wire) as client:
        items = await collected(client.meter_charges.get_meter_charges(WALLET, query))
        assert len(items) == 2
    sent = api_requests(wire)
    assert len(sent) == 2
    assert sent[0].url.params["cursor"] == query.cursor
    assert sent[1].url.params["cursor"] == CURSOR
    for request in sent:
        assert dict(request.url.params) == {
            "status": "succeeded",
            "meterNumber": "0268000710262",
            "from": "2026-10-20T08:00:00Z",
            "to": "2026-10-20T08:00:00Z",
            "cursor": request.url.params["cursor"],
            "pageSize": "50",
        }
        assert not request.content
        _wire_signature_verifies(request)
    assert wire.key_document_requests == 0


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_meter_list_empty_defaults_and_invalid_window(mode: str) -> None:
    wire = SignedMockWire(lambda request: answer({"items": [], "nextCursor": None}))
    async with product_client(mode, wire) as client:
        assert await collected(client.meter_charges.get_meter_charges(WALLET)) == []
        assert not api_requests(wire)[0].url.query
        wire.answer = lambda request: problem("validation_failed", 422)
        from anis_partners import ValidationFailedError

        with pytest.raises(ValidationFailedError):
            await resolved(
                client.meter_charges.get_meter_charges_page(
                    WALLET, MeterChargesQuery(from_=NOW, to=NOW + timedelta(days=32))
                )
            )
    assert wire.key_document_requests == 0


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_meter_list_repeated_initial_cursor_is_refused(mode: str) -> None:
    wire = SignedMockWire(lambda request: answer({"items": [], "nextCursor": CURSOR}))
    async with product_client(mode, wire) as client:
        with pytest.raises(MalformedResponseError):
            await collected(client.meter_charges.get_meter_charges(WALLET, MeterChargesQuery(cursor=CURSOR)))
    assert len(api_requests(wire)) == 1


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("null", [False, True], ids=["omitted", "null"])
@pytest.mark.parametrize(
    ("name", "member", "keys"),
    [
        ("meter-succeeded", "receipt", ("receiptNumber", "creditedAmount")),
        ("meter-failed-refunded", "failure", ("message",)),
    ],
)
async def test_meter_getters_tolerate_omitted_and_null_optional_metadata(
    mode: str, null: bool, name: str, member: str, keys: tuple[str, ...]
) -> None:
    package = {
        "id": str(OPERATION),
        "name": "باقة",
        "gecolPackageName": "PKG_100",
        "unitPrice": {"amount": "97.500", "currency": "LYD"},
        "personalPrice": {"amount": "100.000", "currency": "LYD"},
        **({"logo": None} if null else {}),
    }
    wire = SignedMockWire(lambda request: answer({"items": [package], "nextCursor": None}))
    async with product_client(mode, wire) as client:
        page = await resolved(client.meter_charges.get_meter_packages_page(WALLET))
        assert page.items[0].logo is None
        assert page.items[0].to_json() == {key: value for key, value in package.items() if value is not None}
        data = fixture(name)
        for key in keys:
            if null:
                data[member][key] = None
            else:
                data[member].pop(key)
        wire.answer = lambda request: answer(data)
        result = await resolved(client.meter_charges.get(data["operationId"]))
        expected = {**data, member: {key: value for key, value in data[member].items() if value is not None}}
        assert result.to_json() == expected
        if member == "receipt":
            assert result.receipt.receipt_number is None
            assert result.receipt.credited_amount is None
        else:
            assert result.failure.message is None


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("meter", [True, False])
async def test_create_idempotency_conflict_is_unknown_never_not_placed(mode: str, meter: bool) -> None:
    wire = SignedMockWire(lambda request: problem("idempotency_conflict", 409))
    async with product_client(mode, wire) as client:
        result = await resolved(
            _group(client, meter).create(wallet_id=WALLET, operation_id=OPERATION, request=_request(meter))
        )
        assert isinstance(result, (MeterChargeOutcomeUnknown, DirectRechargeOutcomeUnknown))
        assert result.operation_id == OPERATION
        assert isinstance(result.cause, AnisApiError)
        assert result.cause.raw_code == "idempotency_conflict"
        assert result.cause.status == 409
    assert len(api_requests(wire)) == 1


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("meter", [True, False])
@pytest.mark.parametrize("replayed", [False, True])
async def test_resume_idempotency_conflict_is_unknown_when_replayed_too(mode: str, meter: bool, replayed: bool) -> None:
    headers = {"Idempotency-Replayed": "true"} if replayed else None
    wire = SignedMockWire(lambda request: problem("idempotency_conflict", 409, headers))
    async with product_client(mode, wire) as client:
        result = await resolved(
            _group(client, meter).resume(wallet_id=WALLET, operation_id=OPERATION, request=_request(meter))
        )
        assert isinstance(result, (MeterChargeOutcomeUnknown, DirectRechargeOutcomeUnknown))
        assert isinstance(result.cause, AnisApiError)
        assert result.cause.raw_code == "idempotency_conflict"


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    ("meter", "code", "status"),
    [
        (True, "insufficient_balance", 409),
        (True, "meter_rejected", 422),
        (True, "idempotency_conflict", 409),
        (False, "insufficient_balance", 409),
        (False, "amount_out_of_range", 422),
        (False, "idempotency_conflict", 409),
    ],
)
async def test_get_of_a_recorded_refusal_raises_the_typed_error_with_the_replayed_flag(
    mode: str, meter: bool, code: str, status: int
) -> None:
    wire = SignedMockWire(lambda request: problem(code, status, {"Idempotency-Replayed": "true"}))
    async with product_client(mode, wire) as client:
        with pytest.raises(AnisApiError) as caught:
            await resolved(_group(client, meter).get(OPERATION))
        assert caught.value.raw_code == code
        assert caught.value.status == status
        assert caught.value.is_replayed is True
    assert len(api_requests(wire)) == 1


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_failed_charge_with_a_pending_refund_is_read_with_its_amount_and_stays_processing(mode: str) -> None:
    data = fixture("meter-failed-pending")
    data["operationId"], data["walletId"] = str(OPERATION), str(WALLET)
    wire = SignedMockWire(lambda request: answer(data))
    async with product_client(mode, wire) as client:
        read = await resolved(client.meter_charges.get(OPERATION))
        assert read.status is MeterChargeStatus.FAILED
        assert read.refund is not None
        assert read.refund.status is MeterRefundStatus.PENDING
        assert read.refund.amount is not None
        assert read.refund.amount.amount == Decimal("97.500")
        assert read.to_json() == data
        result = await resolved(
            client.meter_charges.resume(wallet_id=WALLET, operation_id=OPERATION, request=meter_request())
        )
        assert isinstance(result, MeterChargeProcessing)
        assert result.charge.to_json() == data
