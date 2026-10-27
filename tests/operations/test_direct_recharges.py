"""Signed direct recharge reads, recipient correction and unsigned operation collections."""

from dataclasses import replace
from datetime import timedelta
from typing import Any

import httpx
import pytest

from anis_partners import (
    AnisApiError,
    DirectRecharge,
    DirectRechargeAccepted,
    DirectRechargeFinal,
    DirectRechargeProcessing,
    DirectRechargesQuery,
    DirectRechargeStatus,
    MalformedResponseError,
    UnverifiableResponseError,
    UpdateDirectRechargeRecipientRequest,
    ValidationFailedError,
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
    problem,
    product_client,
    recharge_request,
    resolved,
)
from tests.support.sdk_wire import SignedMockWire, WireAnswer

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "status", [state for state in DirectRechargeStatus if state is not DirectRechargeStatus.UNKNOWN]
)
async def test_direct_recharge_merged_states_and_finality(mode: str, status: Any) -> None:
    data = full_read(False, status.value)
    wire = SignedMockWire(lambda request: answer(data))
    async with product_client(mode, wire) as client:
        read = await resolved(client.direct_recharges.get(OPERATION))
        assert isinstance(read, DirectRecharge)
        assert read.status is status
        assert read.exchange_rate == "0.155000"
        assert read.payout.amount == "1500.000"
        assert read.payout.currency.name == "جنيه مصري"
        result = await resolved(
            client.direct_recharges.resume(wallet_id=WALLET, operation_id=OPERATION, request=recharge_request())
        )
        final = status in {
            DirectRechargeStatus.PAYMENT_FAILED,
            DirectRechargeStatus.COMPLETED,
            DirectRechargeStatus.REJECTED_WITH_REFUND,
        }
        assert isinstance(result, DirectRechargeFinal if final else DirectRechargeProcessing)


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_direct_recharge_partial_refund_is_not_completion(mode: str) -> None:
    data = fixture("circle-partially-refunded")
    data["operationId"] = str(OPERATION)
    wire = SignedMockWire(lambda request: answer(data))
    async with product_client(mode, wire) as client:
        result = await resolved(
            client.direct_recharges.resume(wallet_id=WALLET, operation_id=OPERATION, request=recharge_request())
        )
        assert isinstance(result, DirectRechargeProcessing)
        assert isinstance(result.recharge, DirectRecharge)
        assert result.recharge.partial_refund is not None
        assert result.recharge.partial_refund.to_json() == data["partialRefund"]
        wire.answer = lambda request: answer(accepted(False), 202)
        assert isinstance(await resolved(client.direct_recharges.get(OPERATION)), DirectRechargeAccepted)


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_circle_patch_signs_recipient_bytes_without_idempotency(mode: str) -> None:
    wire = SignedMockWire(
        lambda request: answer(accepted(False), 202, {"Location": f"/v1/direct-recharges/{OPERATION}"})
    )
    request = UpdateDirectRechargeRecipientRequest(recharge_request().recipient)
    async with product_client(mode, wire) as client:
        result = await resolved(client.direct_recharges.update_recipient(OPERATION, request))
        assert isinstance(result, DirectRechargeProcessing)
        assert isinstance(result.recharge, DirectRechargeAccepted)
        assert result.recharge.to_json() == accepted(False)
        assert result.location == f"/v1/direct-recharges/{OPERATION}"
    sent = api_requests(wire)
    assert len(sent) == 1
    assert sent[0].method == "PATCH"
    assert sent[0].url.path == f"/v1/direct-recharges/{OPERATION}/recipient"
    assert sent[0].content == b'{"recipient":[{"key":"recipient_number","value":"01012345678"}]}'
    assert "Idempotency-Key" not in sent[0].headers
    _wire_signature_verifies(sent[0])


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "fields", [None, {}, {"recipient_number": "رقم غير صحيح", "FutureKey": "Future"}, ["invalid"], "invalid"]
)
async def test_recipient_validation_preserves_raw_extensions(mode: str, fields: object) -> None:
    extensions = {} if fields is None else {"fields": fields, "future": "kept"}
    wire = SignedMockWire(lambda request: problem("validation_failed", 422, extensions=extensions))
    async with product_client(mode, wire) as client:
        with pytest.raises(ValidationFailedError) as caught:
            await resolved(
                client.direct_recharges.update_recipient(
                    OPERATION, UpdateDirectRechargeRecipientRequest(recharge_request().recipient)
                )
            )
        assert caught.value.problem.extensions == extensions
        assert "رقم غير صحيح" not in str(caught.value)
    assert len(api_requests(wire)) == 1


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("signing", ["gateway", "never"])
async def test_recipient_refusal_requires_signature(mode: str, signing: Any) -> None:
    wire = SignedMockWire(lambda request: problem("direct_recharge_not_suspended", 409), signing=signing)
    async with product_client(mode, wire) as client:
        with pytest.raises(AnisApiError if signing == "gateway" else UnverifiableResponseError):
            await resolved(
                client.direct_recharges.update_recipient(
                    OPERATION, UpdateDirectRechargeRecipientRequest(recharge_request().recipient)
                )
            )


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_direct_recharge_list_filters_pages_defaults_and_validation(mode: str) -> None:
    count = 0
    data = fixture("get-direct-recharges")

    def respond(request: httpx.Request) -> WireAnswer:
        nonlocal count
        count += 1
        return answer({**data, "nextCursor": CURSOR if count == 1 else None})

    wire = SignedMockWire(respond)
    query = DirectRechargesQuery(DirectRechargeStatus.COMPLETED, OPERATION, NOW, NOW, cursor="initial", page_size=100)
    async with product_client(mode, wire) as client:
        items = await collected(client.direct_recharges.get_direct_recharges(WALLET, query))
        assert len(items) == 2
        assert items[0].has_partial_refund is False
        wire.answer = lambda request: answer({"items": [], "nextCursor": None})
        assert await collected(client.direct_recharges.get_direct_recharges(WALLET)) == []
        assert not api_requests(wire)[-1].url.query
        wire.answer = lambda request: answer({"items": [], "nextCursor": CURSOR})
        with pytest.raises(MalformedResponseError):
            await collected(client.direct_recharges.get_direct_recharges(WALLET, replace(query, cursor=CURSOR)))
        wire.answer = lambda request: problem("validation_failed", 422)
        with pytest.raises(ValidationFailedError):
            await resolved(
                client.direct_recharges.get_direct_recharges_page(WALLET, replace(query, to=NOW + timedelta(days=32)))
            )
    sent = api_requests(wire)
    for req in sent[:2]:
        assert req.url.params["status"] == "completed"
        assert req.url.params["productId"] == str(OPERATION)
        assert req.url.params["pageSize"] == "100"
        assert req.url.params["from"] == "2026-10-20T08:00:00Z"
        assert req.url.params["to"] == "2026-10-20T08:00:00Z"
        assert not req.content
        _wire_signature_verifies(req)
    assert sent[1].url.params["cursor"] == CURSOR
    assert wire.key_document_requests == 0


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("null_label", [False, True], ids=["omitted", "null"])
async def test_empty_recipient_create_patch_and_saved_intent_recovery(mode: str, null_label: bool) -> None:
    import json

    from anis_partners import CreateDirectRechargeRequest, DirectRechargeFinal, DirectRechargeRecipientInput

    request = replace(recharge_request(), recipient=(DirectRechargeRecipientInput("OptionalField", ""),))
    saved = json.dumps(request.to_json())
    recovered = CreateDirectRechargeRequest.from_json(saved)
    assert recovered == request
    data = full_read(False)
    data["recipient"] = [{"key": "OptionalField", "value": "", **({"name": None} if null_label else {})}]
    wire = SignedMockWire(lambda sent: answer(data))
    async with product_client(mode, wire) as client:
        created = await resolved(
            client.direct_recharges.create(wallet_id=WALLET, operation_id=OPERATION, request=request)
        )
        resumed = await resolved(
            client.direct_recharges.resume(wallet_id=WALLET, operation_id=OPERATION, request=recovered)
        )
        assert isinstance(created, DirectRechargeFinal)
        assert isinstance(resumed, DirectRechargeFinal)
        read = await resolved(client.direct_recharges.get(OPERATION))
        location = f"/v1/direct-recharges/{OPERATION}"
        wire.answer = lambda sent: answer(accepted(False), 202, {"Location": location})
        patched = await resolved(
            client.direct_recharges.update_recipient(OPERATION, UpdateDirectRechargeRecipientRequest(request.recipient))
        )
        assert isinstance(patched, DirectRechargeProcessing)
        assert isinstance(patched.recharge, DirectRechargeAccepted)
        assert patched.recharge.to_json() == accepted(False)
        assert patched.location == location
        wire.answer = lambda sent: answer(data)
        after_patch = await resolved(client.direct_recharges.get(patched.operation_id))
        for result in (created.recharge, resumed.recharge, read, after_patch):
            assert result.recipient[0].name is None
            assert result.recipient[0].value == ""
            assert result.to_json()["recipient"] == [{"key": "OptionalField", "value": ""}]
    sent = api_requests(wire)
    assert sent[0].content == sent[1].content
    assert json.loads(sent[0].content)["recipient"] == [{"key": "OptionalField", "value": ""}]
    assert sent[0].headers["Idempotency-Key"] == sent[1].headers["Idempotency-Key"] == str(OPERATION)
    assert json.loads(sent[3].content) == {"recipient": [{"key": "OptionalField", "value": ""}]}
    for captured in sent:
        _wire_signature_verifies(captured)


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_recipient_patch_returns_processing_then_explicit_read(mode: str) -> None:
    processing = accepted(False)
    location = f"/v1/direct-recharges/{OPERATION}"
    wire = SignedMockWire(lambda request: answer(processing, 202, {"Location": location, "Retry-After": "5"}))
    patch = UpdateDirectRechargeRecipientRequest(recharge_request().recipient)
    async with product_client(mode, wire) as client:
        result = await resolved(client.direct_recharges.update_recipient(OPERATION, patch))
        assert isinstance(result, DirectRechargeProcessing)
        assert isinstance(result.recharge, DirectRechargeAccepted)
        assert result.recharge.to_json() == processing
        assert result.location == location
        assert len(api_requests(wire)) == 1
        wire.answer = lambda request: answer(full_read(False, "inProgress"))
        read = await resolved(client.direct_recharges.get(result.operation_id))
        assert isinstance(read, DirectRecharge)
        assert read.to_json() == full_read(False, "inProgress")
    sent = api_requests(wire)
    assert [request.method for request in sent] == ["PATCH", "GET"]
    assert sent[0].url.path == location + "/recipient"
    assert sent[1].url.path == location
    assert sent[0].content == b'{"recipient":[{"key":"recipient_number","value":"01012345678"}]}'
    assert "Idempotency-Key" not in sent[0].headers
    for request in sent:
        _wire_signature_verifies(request)


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "bad",
    [
        "wrong-id",
        "wrong-type",
        "extra-member",
        "full-read",
        "wrong-status",
        "200-exchange",
        "missing-location",
        "empty-location",
        "blank-location",
    ],
)
async def test_recipient_patch_rejects_malformed_processing_without_retry(mode: str, bad: str) -> None:
    data = accepted(False)
    status = 202
    if bad == "wrong-id":
        data["operationId"] = str(WALLET)
    elif bad == "wrong-type":
        data["operationType"] = "meterCharge"
    elif bad == "extra-member":
        data["recipient"] = []
    elif bad == "full-read":
        data = full_read(False, "inProgress")
    elif bad == "200-exchange":
        status, data = 200, full_read(False, "inProgress")
    elif bad == "wrong-status":
        status = 200
    headers = None if bad == "missing-location" else {"Location": f"/v1/direct-recharges/{OPERATION}"}
    if bad in {"empty-location", "blank-location"}:
        headers = {"Location": "" if bad == "empty-location" else "   "}
    wire = SignedMockWire(lambda request: answer(data, status, headers))
    async with product_client(mode, wire) as client:
        with pytest.raises(MalformedResponseError):
            await resolved(
                client.direct_recharges.update_recipient(
                    OPERATION, UpdateDirectRechargeRecipientRequest(recharge_request().recipient)
                )
            )
    assert len(api_requests(wire)) == 1


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("bad_signature", ["missing", "bad-digest", "tampered-location", "tampered-status"])
async def test_recipient_processing_requires_signature_without_retry(mode: str, bad_signature: str) -> None:
    headers = {"Location": f"/v1/direct-recharges/{OPERATION}"}
    if bad_signature == "bad-digest":
        headers["Content-Digest"] = "sha-256=:AAAA:"
    wire = SignedMockWire(
        lambda request: answer(accepted(False), 202, headers),
        signing="never" if bad_signature == "missing" else "gateway",
    )
    original = wire.handle

    def tamper(request: httpx.Request) -> httpx.Response:
        response = original(request)
        if request.method == "PATCH":
            if bad_signature == "tampered-location":
                response.headers["Location"] = f"/v1/direct-recharges/{WALLET}"
            elif bad_signature == "tampered-status":
                response.status_code = 200
        return response

    wire.transport = httpx.MockTransport(tamper)
    async with product_client(mode, wire) as client:
        with pytest.raises(UnverifiableResponseError) as caught:
            await resolved(
                client.direct_recharges.update_recipient(
                    OPERATION, UpdateDirectRechargeRecipientRequest(recharge_request().recipient)
                )
            )
    expected = {
        "missing": "signature_missing",
        "bad-digest": "content_digest_mismatch",
        "tampered-location": "signature_invalid",
        "tampered-status": "signature_invalid",
    }
    assert caught.value.failure.value == expected[bad_signature]
    assert len(api_requests(wire)) == 1


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("retry_after", [None, "0", "7"])
async def test_recipient_patch_reuses_create_acknowledgement_type(mode: str, retry_after: str | None) -> None:
    from anis_partners import MeterChargeAccepted, MeterChargeProcessing
    from tests.support.products import meter_request

    location = f"/v1/direct-recharges/{OPERATION}"
    headers = {"Location": location}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    wire = SignedMockWire(lambda request: answer(accepted(request.url.path.endswith("/meter-charges")), 202, headers))
    async with product_client(mode, wire) as client:
        meter = await resolved(
            client.meter_charges.create(wallet_id=WALLET, operation_id=OPERATION, request=meter_request())
        )
        created = await resolved(
            client.direct_recharges.create(wallet_id=WALLET, operation_id=OPERATION, request=recharge_request())
        )
        patched = await resolved(
            client.direct_recharges.update_recipient(
                OPERATION, UpdateDirectRechargeRecipientRequest(recharge_request().recipient)
            )
        )
        assert isinstance(meter, MeterChargeProcessing)
        assert isinstance(meter.charge, MeterChargeAccepted)
        assert meter.charge.to_json() == accepted(True)
        assert type(patched) is type(created) is DirectRechargeProcessing
        assert isinstance(patched.recharge, DirectRechargeAccepted)
        assert type(patched.recharge) is type(created.recharge)
        assert patched.recharge.to_json() == created.recharge.to_json() == accepted(False)
        assert patched.operation_id == created.operation_id == OPERATION
        assert patched.location == created.location == location
        assert (
            patched.retry_after
            == created.retry_after
            == timedelta(seconds=int(retry_after) if retry_after is not None else 5)
        )
    sent = api_requests(wire)
    assert [request.method for request in sent] == ["POST", "POST", "PATCH"]
    assert "Idempotency-Key" not in sent[-1].headers
    for request in sent:
        _wire_signature_verifies(request)
