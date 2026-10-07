"""Pin which answers Anis signs: signed routes stay strictly verified, information reads are read unsigned."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

import httpx
import pytest

from anis_partners import (
    PARTNER_ROUTES,
    AnisApiError,
    AnisEnrollmentClient,
    AnisPartnersClient,
    AsyncAnisEnrollmentClient,
    AsyncAnisPartnersClient,
    AuthorizationError,
    ClientOptions,
    OrderOutcomeUnknown,
    PartnerRoute,
    RateLimitedError,
    ResourceNotFoundError,
    ResponseVerificationFailure,
    UnverifiableResponseError,
)
from anis_partners.operations.transport import RequestSpec
from anis_partners.signing.signature_profile import SignatureProfile
from tests.support.partner import CARD_SOLD, OPERATION, SIGNER, WALLET
from tests.support.partner import order as _order
from tests.support.sdk_wire import SignedMockWire, WireAnswer

KEY_DOCUMENT = "/.well-known/partner-signing-keys.json"
CATEGORY = UUID("11111111-1111-1111-1111-111111111111")
SUBCATEGORY = UUID("22222222-2222-2222-2222-222222222222")
INVITATION = UUID("3f2a9c14-8d6e-4b21-9f07-5c8ab2d61e43")
TOKEN = "-".join(("enrollment", "test", "token"))

#: The gateway's published lists (anis.partners-consumers-gateway README "Response signing"), written out here.
SIGNED_ROUTES = {
    ("POST", "/v1/wallets/{walletId}/orders"),
    ("GET", "/v1/orders/{operationId}"),
    ("POST", "/v1/wallets/{walletId}/cards/{soldCardId}/reveal"),
    ("POST", "/v1/wallets/{walletId}/invoices/{invoiceId}/cards/reveal"),
    ("GET", "/v1/enrollments/{invitationId}"),
    ("POST", "/v1/enrollments/{invitationId}/keys"),
    ("POST", "/v1/enrollments/{invitationId}/proof"),
    ("GET", "/v1/enrollments/{invitationId}/status"),
    ("POST", "/v1/diagnostics/signature"),
}
UNSIGNED_ROUTES = {
    ("GET", "/v1/profile"),
    ("GET", "/v1/wallets"),
    ("GET", "/v1/wallets/{walletId}"),
    ("GET", "/v1/wallets/{walletId}/catalog/categories"),
    ("GET", "/v1/wallets/{walletId}/catalog/categories/{categoryId}/subcategories"),
    ("GET", "/v1/wallets/{walletId}/catalog/subcategories/{subcategoryId}"),
    ("GET", "/v1/wallets/{walletId}/catalog/subcategories/{subcategoryId}/cards"),
    ("GET", "/v1/wallets/{walletId}/cards"),
    ("GET", "/v1/wallets/{walletId}/cards/{soldCardId}"),
    ("GET", "/.well-known/partner-signing-keys.json"),
}

_PROFILE = (
    b'{"partner":{"id":"7c9e6679-7425-40de-944b-e07fc1f90ae7"},'
    b'"application":{"id":"16fd2706-8baf-433b-82eb-8c7fada847da","scopes":["profile:read"]}}'
)
_WALLET = (
    b'{"id":"2f1c8a94-6d37-4e52-b8a1-0c9e5d3f7b26","name":"Main","currency":"LYD",'
    b'"balance":{"amount":"1.000","currency":"LYD"}}'
)
_PAGE = b'{"items":[],"nextCursor":null}'
_SUBCATEGORY = b'{"id":"22222222-2222-2222-2222-222222222222","categoryId":"11111111-1111-1111-1111-111111111111"}'
_MASKED_CARD = b'{"id":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046"}'

#: One call per information route; the same callable serves both clients because their operation names match.
Call = Callable[[Any], Any]
INFORMATION_CALLS: list[tuple[str, Call, bytes]] = [
    ("/v1/profile", lambda client: client.profile.get(), _PROFILE),
    ("/v1/wallets", lambda client: client.wallets.list_page(), _PAGE),
    (f"/v1/wallets/{WALLET}", lambda client: client.wallets.get(WALLET), _WALLET),
    (
        f"/v1/wallets/{WALLET}/catalog/categories",
        lambda client: client.catalogue.list_categories_page(WALLET),
        _PAGE,
    ),
    (
        f"/v1/wallets/{WALLET}/catalog/categories/{CATEGORY}/subcategories",
        lambda client: client.catalogue.list_subcategories_page(WALLET, CATEGORY),
        _PAGE,
    ),
    (
        f"/v1/wallets/{WALLET}/catalog/subcategories/{SUBCATEGORY}",
        lambda client: client.catalogue.get_subcategory(WALLET, SUBCATEGORY),
        _SUBCATEGORY,
    ),
    (
        f"/v1/wallets/{WALLET}/catalog/subcategories/{SUBCATEGORY}/cards",
        lambda client: client.catalogue.list_cards_page(WALLET, SUBCATEGORY),
        _PAGE,
    ),
    (f"/v1/wallets/{WALLET}/cards", lambda client: client.owned_cards.list_page(WALLET), _PAGE),
    (f"/v1/wallets/{WALLET}/cards/{CARD_SOLD}", lambda client: client.owned_cards.get(WALLET, CARD_SOLD), _MASKED_CARD),
]
_INFORMATION_IDS = [path for path, _, _ in INFORMATION_CALLS]

#: Signed partner reads and mutations whose answers must verify; the order is covered separately below.
SIGNED_CALLS: list[tuple[str, Call]] = [
    (f"/v1/orders/{OPERATION}", lambda client: client.orders.get(OPERATION)),
    (f"/v1/wallets/{WALLET}/cards/{CARD_SOLD}/reveal", lambda client: client.owned_cards.reveal(WALLET, CARD_SOLD)),
    (
        f"/v1/wallets/{WALLET}/invoices/{CARD_SOLD}/cards/reveal",
        lambda client: client.owned_cards.reveal_invoice(WALLET, CARD_SOLD),
    ),
    ("/v1/diagnostics/signature", lambda client: client.diagnostics.check_signature()),
]
_SIGNED_IDS = [path for path, _ in SIGNED_CALLS]

#: Unsigned refusals on information routes and the typed error each must still map to.
REFUSALS: list[tuple[int, str, dict[str, str], type[AnisApiError]]] = [
    (404, "resource_not_found", {}, ResourceNotFoundError),
    (403, "insufficient_scope", {}, AuthorizationError),
    (429, "rate_limited", {"Retry-After": "7"}, RateLimitedError),
]
_REFUSAL_IDS = [code for _, code, _, _ in REFUSALS]


def _problem(status: int, code: str) -> bytes:
    return f'{{"type":"about:blank","title":"refused","status":{status},"code":"{code}"}}'.encode()


def _api_paths(wire: SignedMockWire) -> list[str]:
    return [request.url.path for request in wire.requests if request.url.path != KEY_DOCUMENT]


def _sync(wire: SignedMockWire | httpx.MockTransport) -> tuple[AnisPartnersClient, httpx.Client]:
    transport = wire.transport if isinstance(wire, SignedMockWire) else wire
    http = httpx.Client(transport=transport)
    return AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http), http


def _async(wire: SignedMockWire | httpx.MockTransport) -> tuple[AsyncAnisPartnersClient, httpx.AsyncClient]:
    transport = wire.transport if isinstance(wire, SignedMockWire) else wire
    http = httpx.AsyncClient(transport=transport)
    return AsyncAnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http), http


def test_answer_signing_is_set_per_route_exactly_as_the_gateway_publishes() -> None:
    """Fail when a route moves between the signed and unsigned sets without a matching gateway change."""
    signed = {(route.method, route.template) for route in PARTNER_ROUTES if route.signs_response}
    unsigned = {(route.method, route.template) for route in PARTNER_ROUTES if not route.signs_response}
    assert signed == SIGNED_ROUTES
    assert unsigned == UNSIGNED_ROUTES
    assert len(PARTNER_ROUTES) == len(SIGNED_ROUTES) + len(UNSIGNED_ROUTES)


def test_a_route_or_request_without_a_stated_answer_policy_fails_closed() -> None:
    """Default to verification so a route added or a request built without a decision is never read unsigned."""
    assert PartnerRoute("GET", "/v1/new", SignatureProfile.SAFE_READ).signs_response is True
    assert RequestSpec("GET", "/v1/profile", "/v1/profile", SignatureProfile.SAFE_READ).signs_response is True


@pytest.mark.parametrize(("path", "call", "body"), INFORMATION_CALLS, ids=_INFORMATION_IDS)
def test_sync_information_route_reads_its_unsigned_answer(path: str, call: Call, body: bytes) -> None:
    """Return the unsigned information answer while still signing the request and never fetching response keys."""
    wire = SignedMockWire(lambda request: WireAnswer(body=body))
    client, http = _sync(wire)
    try:
        assert call(client) is not None
        request = next(item for item in wire.requests if item.url.path == path)
        assert request.headers.get("Signature")
        assert request.headers.get("Signature-Input")
        assert _api_paths(wire) == [path]
        assert wire.key_document_requests == 0
    finally:
        client.close()
        http.close()


@pytest.mark.anyio
@pytest.mark.parametrize(("path", "call", "body"), INFORMATION_CALLS, ids=_INFORMATION_IDS)
async def test_async_information_route_reads_its_unsigned_answer(path: str, call: Call, body: bytes) -> None:
    """Apply the same per-route answer policy in the asynchronous client."""
    wire = SignedMockWire(lambda request: WireAnswer(body=body))
    client, http = _async(wire)
    try:
        assert await cast(Awaitable[object], call(client)) is not None
        request = next(item for item in wire.requests if item.url.path == path)
        assert request.headers.get("Signature")
        assert _api_paths(wire) == [path]
        assert wire.key_document_requests == 0
    finally:
        await client.aclose()
        await http.aclose()


def test_information_route_answer_is_unsigned_on_the_wire() -> None:
    """Keep the in-memory gateway honest: information answers carry a digest and request id but no signature."""
    wire = SignedMockWire(lambda request: WireAnswer(body=_PROFILE))
    response = wire.handle(httpx.Request("GET", "https://partners.test/v1/profile"))
    assert "signature" not in response.headers
    assert "signature-input" not in response.headers
    assert response.headers["content-digest"].startswith("sha-256=:")
    assert response.headers["x-request-id"]


@pytest.mark.parametrize("signature", ["valid", "garbage"])
def test_sync_information_route_ignores_an_unexpected_signature(signature: str) -> None:
    """Never fail an information read because an answer unexpectedly carries signature fields."""
    wire = SignedMockWire(lambda request: WireAnswer(body=_PROFILE), signing="always")

    def handler(request: httpx.Request) -> httpx.Response:
        response = wire.handle(request)
        if signature == "garbage" and request.url.path != KEY_DOCUMENT:
            response.headers["Signature-Input"] = "sig1=(not a signature input)"
            response.headers["Signature"] = "sig1=:AAAA:"
        return response

    client, http = _sync(httpx.MockTransport(handler))
    try:
        assert client.profile.get().application is not None
        assert wire.key_document_requests == 0
    finally:
        client.close()
        http.close()


@pytest.mark.anyio
async def test_async_information_route_ignores_an_unexpected_signature() -> None:
    """Never fail an asynchronous information read because an answer carries an unverifiable signature."""
    wire = SignedMockWire(lambda request: WireAnswer(body=_WALLET), signing="always")

    def handler(request: httpx.Request) -> httpx.Response:
        response = wire.handle(request)
        response.headers["Signature"] = "sig1=:AAAA:"
        return response

    client, http = _async(httpx.MockTransport(handler))
    try:
        assert (await client.wallets.get(WALLET)).name == "Main"
        assert wire.key_document_requests == 0
    finally:
        await client.aclose()
        await http.aclose()


@pytest.mark.parametrize(("status", "code", "headers", "error_type"), REFUSALS, ids=_REFUSAL_IDS)
def test_sync_unsigned_information_refusal_maps_to_its_typed_error(
    status: int, code: str, headers: dict[str, str], error_type: type[AnisApiError]
) -> None:
    """Map an unsigned information refusal exactly as before: typed error, code, status, and retry delay."""
    wire = SignedMockWire(lambda request: WireAnswer(status, _problem(status, code), headers))
    client, http = _sync(wire)
    try:
        with pytest.raises(error_type) as caught:
            client.wallets.get(WALLET)
        assert caught.value.code.value == code
        assert caught.value.status == status
        if "Retry-After" in headers:
            assert caught.value.retry_after == timedelta(seconds=7)
        assert wire.key_document_requests == 0
    finally:
        client.close()
        http.close()


@pytest.mark.anyio
@pytest.mark.parametrize(("status", "code", "headers", "error_type"), REFUSALS, ids=_REFUSAL_IDS)
async def test_async_unsigned_information_refusal_maps_to_its_typed_error(
    status: int, code: str, headers: dict[str, str], error_type: type[AnisApiError]
) -> None:
    """Map unsigned asynchronous information refusals through the same shared refusal rules."""
    wire = SignedMockWire(lambda request: WireAnswer(status, _problem(status, code), headers))
    client, http = _async(wire)
    try:
        with pytest.raises(error_type) as caught:
            await client.owned_cards.get(WALLET, CARD_SOLD)
        assert caught.value.code.value == code
        assert caught.value.status == status
        assert wire.key_document_requests == 0
    finally:
        await client.aclose()
        await http.aclose()


@pytest.mark.parametrize(("path", "call"), SIGNED_CALLS, ids=_SIGNED_IDS)
@pytest.mark.parametrize("status", [200, 429])
def test_sync_signed_route_without_a_signature_is_refused(path: str, call: Call, status: int) -> None:
    """Refuse a signed route's success or refusal that arrives unsigned, before its body can be used."""
    answer = WireAnswer(status, b"{}" if status == 200 else _problem(429, "rate_limited"), {"Retry-After": "1"})
    wire = SignedMockWire(lambda request: answer, signing="never")
    client, http = _sync(wire)
    try:
        with pytest.raises(UnverifiableResponseError) as caught:
            call(client)
        assert caught.value.failure is ResponseVerificationFailure.SIGNATURE_MISSING
        assert _api_paths(wire) == [path]
    finally:
        client.close()
        http.close()


@pytest.mark.anyio
@pytest.mark.parametrize(("path", "call"), SIGNED_CALLS, ids=_SIGNED_IDS)
async def test_async_signed_route_without_a_signature_is_refused(path: str, call: Call) -> None:
    """Keep the asynchronous client's signed routes strict: no signature is never treated as an unsigned answer."""
    wire = SignedMockWire(lambda request: WireAnswer(429, _problem(429, "rate_limited")), signing="never")
    client, http = _async(wire)
    try:
        with pytest.raises(UnverifiableResponseError) as caught:
            await cast(Awaitable[object], call(client))
        assert caught.value.failure is ResponseVerificationFailure.SIGNATURE_MISSING
        assert _api_paths(wire) == [path]
    finally:
        await client.aclose()
        await http.aclose()


def test_sync_unsigned_order_answer_is_an_unknown_outcome() -> None:
    """Treat an unsigned order answer as unverifiable, so the sale may have happened and must be resumed."""
    wire = SignedMockWire(lambda request: WireAnswer(201, b'{"status":"completed"}'), signing="never")
    client, http = _sync(wire)
    try:
        outcome = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
        assert isinstance(outcome, OrderOutcomeUnknown)
        assert isinstance(outcome.cause, UnverifiableResponseError)
        assert outcome.cause.failure is ResponseVerificationFailure.SIGNATURE_MISSING
    finally:
        client.close()
        http.close()


@pytest.mark.anyio
async def test_async_unsigned_order_answer_is_an_unknown_outcome() -> None:
    """Treat an unsigned asynchronous order refusal as unverifiable rather than a definitive refusal."""
    wire = SignedMockWire(lambda request: WireAnswer(409, _problem(409, "insufficient_balance")), signing="never")
    client, http = _async(wire)
    try:
        outcome = await client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
        assert isinstance(outcome, OrderOutcomeUnknown)
        assert isinstance(outcome.cause, UnverifiableResponseError)
        assert outcome.cause.failure is ResponseVerificationFailure.SIGNATURE_MISSING
    finally:
        await client.aclose()
        await http.aclose()


def test_sync_unsigned_enrollment_answer_is_refused() -> None:
    """Keep enrollment answers signed: an unsigned one would let a forged state reach key setup."""
    body = b'{"invitationId":"3f2a9c14-8d6e-4b21-9f07-5c8ab2d61e43","state":"pendingPublicKey"}'
    wire = SignedMockWire(lambda request: WireAnswer(body=body), signing="never")
    http = httpx.Client(transport=wire.transport)
    try:
        with AnisEnrollmentClient("https://partners.test", INVITATION, TOKEN, http_client=http) as client:
            with pytest.raises(UnverifiableResponseError) as caught:
                client.get()
            assert caught.value.failure is ResponseVerificationFailure.SIGNATURE_MISSING
    finally:
        http.close()


@pytest.mark.anyio
async def test_async_unsigned_enrollment_status_is_refused() -> None:
    """Keep asynchronous enrollment status answers signed so an unsigned `active` is never believed."""
    body = b'{"invitationId":"3f2a9c14-8d6e-4b21-9f07-5c8ab2d61e43","state":"active"}'
    wire = SignedMockWire(lambda request: WireAnswer(body=body), signing="never")
    http = httpx.AsyncClient(transport=wire.transport)
    try:
        async with AsyncAnisEnrollmentClient("https://partners.test", INVITATION, TOKEN, http_client=http) as client:
            with pytest.raises(UnverifiableResponseError) as caught:
                await client.get_status()
            assert caught.value.failure is ResponseVerificationFailure.SIGNATURE_MISSING
    finally:
        await http.aclose()
