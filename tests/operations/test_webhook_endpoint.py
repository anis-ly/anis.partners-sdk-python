"""Endpoint changes use nonce signing once and keep all three required response members."""

from typing import Any

import httpx
import pytest

from anis_partners import AnisApiError, SetWebhookEndpointRequest, UnverifiableResponseError
from tests.operations.test_signed_wire_capture import _wire_signature_verifies
from tests.support.partner import OPERATION
from tests.support.products import NOW, answer, api_requests, problem, product_client, resolved
from tests.support.sdk_wire import SignedMockWire, WireAnswer

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("status", ["notConfigured", "pendingVerification", "verified", "disabled"])
async def test_endpoint_get_is_unsigned_and_preserves_nulls(mode: str, status: Any) -> None:
    data = {"url": None, "status": status, "generation": None}
    wire = SignedMockWire(lambda request: answer(data))
    async with product_client(mode, wire) as client:
        assert (await resolved(client.webhook_endpoint.get())).to_json() == data
    sent = api_requests(wire)
    assert len(sent) == 1
    assert sent[0].content == b""
    assert "Idempotency-Key" not in sent[0].headers
    _wire_signature_verifies(sent[0])
    assert wire.key_document_requests == 0


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_endpoint_put_and_test_sign_exact_bytes_without_purchase_key(mode: str) -> None:
    url = "https://receiver.test/events?source=partner"

    def respond(request: httpx.Request) -> WireAnswer:
        if request.method == "PUT":
            return answer({"url": url, "status": "pendingVerification", "generation": 12})
        return answer(
            {
                "id": str(OPERATION),
                "status": "pending",
                "queuedAt": NOW.isoformat().replace("+00:00", "Z"),
                "type": "webhook_endpoint.test",
            },
            202,
        )

    wire = SignedMockWire(respond)
    async with product_client(mode, wire) as client:
        result = await resolved(client.webhook_endpoint.set(SetWebhookEndpointRequest(url)))
        assert result.generation == 12
        result = await resolved(client.webhook_endpoint.test())
        assert result.id == OPERATION
        assert result.status == "pending"
        assert set(result.to_json()) == {"id", "status", "queuedAt", "type"}
    sent = api_requests(wire)
    assert sent[0].content == b'{"url":"https://receiver.test/events?source=partner"}'
    assert sent[1].content == b"{}"
    assert sent[0].method == "PUT"
    assert sent[1].method == "POST"
    assert sent[0].headers["Nonce"] != sent[1].headers["Nonce"]
    for req in sent:
        assert "Idempotency-Key" not in req.headers
        _wire_signature_verifies(req)


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    ("method", "code", "status"),
    [("set", "webhook_endpoint_invalid", 422), ("test", "webhook_endpoint_unverified", 409)],
)
@pytest.mark.parametrize("signing", ["gateway", "never"])
async def test_endpoint_refusals_require_signed_answers(
    mode: str, method: str, code: str, status: Any, signing: Any
) -> None:
    wire = SignedMockWire(lambda request: problem(code, status), signing=signing)
    async with product_client(mode, wire) as client:
        with pytest.raises(AnisApiError if signing == "gateway" else UnverifiableResponseError):
            await resolved(
                client.webhook_endpoint.set(SetWebhookEndpointRequest("https://receiver.test"))
                if method == "set"
                else client.webhook_endpoint.test()
            )
    assert len(api_requests(wire)) == 1


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_endpoint_transport_failure_has_no_automatic_replay(mode: str) -> None:
    def respond(request: httpx.Request) -> WireAnswer:
        raise httpx.ReadTimeout("No answer")

    wire = SignedMockWire(respond)
    async with product_client(mode, wire) as client:
        with pytest.raises(httpx.ReadTimeout):
            await resolved(client.webhook_endpoint.set(SetWebhookEndpointRequest("https://receiver.test")))
    assert len(api_requests(wire)) == 1
