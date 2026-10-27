"""Verify that client signatures cover bytes and URL facts handed to HTTPX."""

import base64
import hashlib
import re
from datetime import UTC, datetime

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from anis_partners import AcceptLanguage, AnisPartnersClient, ClientOptions, OrderCompleted
from tests.support.partner import CARD_SOLD, OPERATION, SIGNER, WALLET, order
from tests.support.sdk_wire import SignedMockWire, WireAnswer


def _wire_signature_verifies(request: httpx.Request) -> None:
    """Rebuild the signature base independently from the final HTTPX request representation."""
    signature_input = request.headers["Signature-Input"]
    params = signature_input.removeprefix("sig1=")
    covered_text = params.split(");", 1)[0] + ")"
    components = re.findall(r'"([^\"]+)"', covered_text)
    raw_path, _, query = request.url.raw_path.partition(b"?")
    values: dict[str, str] = {
        "@method": request.method,
        "@authority": request.url.netloc.decode("ascii"),
        "@path": raw_path.decode("ascii"),
        "@query": "?" + query.decode("ascii"),
    }
    values.update({name.lower(): request.headers[name] for name in request.headers})
    lines = [f'"{component}": {values[component]}' for component in components]
    base = ("\n".join([*lines, f'"@signature-params": {params}'])).encode("utf-8")
    envelope = request.headers["Signature"]
    signature = base64.b64decode(envelope.removeprefix("sig1=:").removesuffix(":"), validate=True)
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    public_key = SIGNER._key.public_key()
    public_key.verify(encode_dss_signature(r, s), base, ec.ECDSA(hashes.SHA256()))
    if "Content-Digest" in request.headers:
        expected = "sha-256=:" + base64.b64encode(hashlib.sha256(request.content).digest()).decode("ascii") + ":"
        assert request.headers["Content-Digest"] == expected
    if "Nonce" in request.headers:
        assert f';nonce="{request.headers["Nonce"]}"' in params
    created_match = re.search(r";created=([0-9]+)", params)
    assert created_match is not None
    created = int(created_match.group(1))
    assert request.headers["X-Anis-Date"] == datetime.fromtimestamp(created, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if "Idempotency-Key" in request.headers:
        assert request.headers["Idempotency-Key"] == str(OPERATION)
    for name in ("Signature", "Signature-Input", "X-Anis-Date", "Content-Digest", "Nonce", "Idempotency-Key"):
        assert len(request.headers.get_list(name)) <= 1


def test_client_signatures_verify_over_the_requests_actually_sent() -> None:
    """Cover a cursor read, bodyless reveal, self-check, and order using their final HTTP requests."""

    def answer(request: httpx.Request) -> WireAnswer:
        if request.url.path.endswith("/reveal"):
            return WireAnswer(body=b'{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"V"}')
        if request.url.path.endswith("/diagnostics/signature"):
            return WireAnswer(body=b'{"routeId":"signature-diagnostic","method":"POST"}')
        if request.url.path.endswith("/orders"):
            return WireAnswer(
                status=201,
                body=b'{"status":"completed","soldCards":[{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"V"}]}',
            )
        return WireAnswer(body=b'{"items":[],"nextCursor":null}')

    wire = SignedMockWire(answer)
    http = httpx.Client(transport=wire.transport, headers={"X-Host-Context": "host-value"})
    client = AnisPartnersClient(
        ClientOptions("https://partners.test:443", accept_language=AcceptLanguage.ENGLISH), SIGNER, http_client=http
    )
    try:
        client.wallets.list_page("page / two")
        client.owned_cards.reveal(WALLET, CARD_SOLD)
        client.diagnostics.check_signature()
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=order())
    finally:
        client.close()
        http.close()

    assert isinstance(result, OrderCompleted)
    requests = [request for request in wire.requests if request.url.path != "/.well-known/partner-signing-keys.json"]
    assert len(requests) == 4
    assert requests[0].url.query == b"cursor=page%20%2F%20two"
    assert requests[0].url.netloc.decode("ascii") == "partners.test"
    assert requests[1].content == b""
    assert requests[2].content == b"{}"
    for request in requests:
        assert request.headers["X-Host-Context"] == "host-value"
        assert request.headers["Accept-Language"] == "en"
        assert request.extensions["timeout"]["read"] == 30.0
        _wire_signature_verifies(request)


def test_all_product_mutation_profiles_cover_transmitted_bytes() -> None:
    """Verify both purchase and signed-change signatures from the final HTTPX request bytes."""
    from anis_partners import SetWebhookEndpointRequest, UpdateDirectRechargeRecipientRequest
    from tests.support.products import NOW, accepted, answer, api_requests, full_read, meter_request, recharge_request

    def respond(request: httpx.Request) -> WireAnswer:
        path = request.url.path
        if path.endswith("/meter-charges"):
            return answer(accepted(), 202)
        if path.endswith("/direct-recharges"):
            return answer(accepted(False), 202)
        if "/meter-charges/" in path:
            return answer(full_read())
        if path.endswith("/recipient"):
            return answer(accepted(False), 202, {"Location": f"/v1/direct-recharges/{OPERATION}"})
        if "/direct-recharges/" in path:
            return answer(full_read(False, "inProgress"))
        if path == "/v1/webhook-endpoint":
            return answer({"url": "https://receiver.test", "status": "verified", "generation": 1})
        return answer({"id": str(OPERATION), "status": "pending", "queuedAt": NOW.isoformat()}, 202)

    wire = SignedMockWire(respond)
    with (
        httpx.Client(transport=wire.transport) as http,
        AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http) as client,
    ):
        client.meter_charges.create(wallet_id=WALLET, operation_id=OPERATION, request=meter_request())
        client.meter_charges.get(OPERATION)
        client.direct_recharges.create(wallet_id=WALLET, operation_id=OPERATION, request=recharge_request())
        client.direct_recharges.get(OPERATION)
        client.direct_recharges.update_recipient(
            OPERATION, UpdateDirectRechargeRecipientRequest(recharge_request().recipient)
        )
        client.webhook_endpoint.set(SetWebhookEndpointRequest("https://receiver.test"))
        client.webhook_endpoint.test()
        client.webhook_events.redeliver(OPERATION)
    sent = api_requests(wire)
    assert len(sent) == 8
    nonces = set()
    for request in sent:
        _wire_signature_verifies(request)
        if request.method != "GET":
            nonces.add(request.headers["Nonce"])
            purchase = request.url.path.endswith(("/meter-charges", "/direct-recharges"))
            assert ("Idempotency-Key" in request.headers) is purchase
    assert len(nonces) == 6
