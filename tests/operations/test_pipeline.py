"""Exercise public sync and async clients through a signed in-memory HTTPX wire."""

from __future__ import annotations

import asyncio
import gzip
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from anis_partners import (
    AnisApiError,
    AnisPartnersClient,
    AsyncAnisPartnersClient,
    ClientOptions,
    CreateOrderRequest,
    InsufficientBalanceError,
    Money,
    OrderCompleted,
    OrderNotPlaced,
    OrderOutcomeUnknown,
    OrderProcessing,
    OrderReplayed,
    PriceChangedError,
    RateLimitedError,
    RequestSigner,
    UnverifiableResponseError,
)
from anis_partners.signing.ecdsa_signature_format import der_to_p1363
from anis_partners.signing.errors import RequestSigningError
from tests.support.sdk_wire import SignedMockWire, WireAnswer

WALLET = UUID("2f1c8a94-6d37-4e52-b8a1-0c9e5d3f7b26")
OPERATION = UUID("9b2e4f17-3c6a-4d58-b0e1-7a5c8d2f6b34")
CARD = UUID("8d4b1e73-9a25-4c60-8f37-6b2e9d5a1c48")
CARD_SOLD = UUID("4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046")


class _Signer:
    """Supply a test-only P-256 key through the same 64-byte signer seam as a partner vault."""

    key_id = "9e96dc41-c715-4cc4-b1aa-836fe42ad0bb"

    def __init__(self) -> None:
        self._key = ec.generate_private_key(ec.SECP256R1())

    def sign(self, data: bytes) -> bytes:
        """Produce the wire encoding expected from an injected signer."""
        return der_to_p1363(self._key.sign(data, ec.ECDSA(hashes.SHA256())))


SIGNER: RequestSigner = _Signer()


def _order(unit: str = "10.500", total: str = "21.000", quantity: int = 2) -> CreateOrderRequest:
    """Create one exact order intent with whole-decimal prices."""
    return CreateOrderRequest(CARD, quantity, Money(Decimal(unit), "LYD"), Money(Decimal(total), "LYD"))


def _client(wire: SignedMockWire) -> tuple[AnisPartnersClient, httpx.Client]:
    http = cast(httpx.Client, wire.client())
    return AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http), http


def test_sync_profile_is_signed_and_returns_only_verified_data() -> None:
    """Check the client signs a safe read and waits for a valid published response key."""
    wire = SignedMockWire(
        lambda request: WireAnswer(
            body=b'{"partner":{"id":"7c9e6679-7425-40de-944b-e07fc1f90ae7"},"application":{"id":"16fd2706-8baf-433b-82eb-8c7fada847da","scopes":["profile:read"]}}'
        )
    )
    client, http = _client(wire)
    try:
        profile = client.profile.get()
        sent = next(request for request in wire.requests if request.url.path == "/v1/profile")
        assert profile.application is not None
        assert profile.application.scopes == ("profile:read",)
        assert sent.headers.get("Signature")
        assert sent.headers.get("Signature-Input")
        assert sent.headers["Accept-Encoding"] == "identity"
        assert "Nonce" not in sent.headers
        assert "Content-Digest" not in sent.headers
        assert wire.key_document_requests == 1
    finally:
        client.close()
        http.close()


def test_reveal_sends_zero_bytes_and_diagnostic_sends_exact_empty_object() -> None:
    """Keep reveal bodies empty while the declared signature diagnostic body remains exactly `{}`."""

    def answer(request: httpx.Request) -> WireAnswer:
        if request.url.path.endswith("/reveal"):
            return WireAnswer(body=b'{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"secret"}')
        return WireAnswer(
            body=b'{"routeId":"signature-diagnostic","method":"POST","coveredComponents":[],"effectiveScopes":[]}'
        )

    wire = SignedMockWire(answer)
    client, http = _client(wire)
    try:
        credential = client.owned_cards.reveal(WALLET, CARD_SOLD)
        diagnostic = client.diagnostics.check_signature()
        reveal = next(request for request in wire.requests if request.url.path.endswith("/reveal"))
        check = next(request for request in wire.requests if request.url.path.endswith("/signature"))
        assert credential.voucher == "secret"
        assert diagnostic.route_id == "signature-diagnostic"
        assert reveal.content == b""
        assert "Content-Type" not in reveal.headers
        assert reveal.headers["Content-Digest"] == "sha-256=:47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=:"
        assert check.content == b"{}"
        assert check.headers["Content-Type"] == "application/json"
    finally:
        client.close()
        http.close()


def test_invoice_reveal_sends_zero_bytes_and_returns_the_verified_collection() -> None:
    """Keep invoice reveal atomic and bodyless so callers receive only the signed complete credential set."""
    wire = SignedMockWire(
        lambda request: WireAnswer(
            body=b'{"items":[{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"V"}]}'
        )
    )
    client, http = _client(wire)
    try:
        result = client.owned_cards.reveal_invoice(WALLET, CARD_SOLD)
        request = next(item for item in wire.requests if item.url.path.endswith("/cards/reveal"))
        assert len(result.items) == 1
        assert result.items[0].voucher == "V"
        assert request.content == b""
        assert "Content-Type" not in request.headers
    finally:
        client.close()
        http.close()


def test_tampered_response_body_is_discarded_before_model_parsing() -> None:
    """Discard content whose signed digest no longer matches instead of exposing tampered credentials."""
    wire = SignedMockWire(
        lambda request: WireAnswer(body=b'{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"V"}')
    )

    def alter(request: httpx.Request) -> httpx.Response:
        response = wire.handle(request)
        if request.url.path == "/.well-known/partner-signing-keys.json":
            return response
        return httpx.Response(
            response.status_code, headers=response.headers, content=b'{"voucher":"tampered"}', request=request
        )

    http = httpx.Client(transport=httpx.MockTransport(alter))
    client = AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http)
    try:
        with pytest.raises(UnverifiableResponseError):
            client.owned_cards.reveal(WALLET, CARD_SOLD)
    finally:
        client.close()
        http.close()


def test_create_order_sends_exact_body_and_caller_operation_id() -> None:
    """Keep the operation id and decimal-string body tied to the signed purchase."""
    body = (
        b'{"operationId":"9b2e4f17-3c6a-4d58-b0e1-7a5c8d2f6b34","status":"completed",'
        b'"soldCards":[{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"V"}]}'
    )
    wire = SignedMockWire(lambda request: WireAnswer(status=201, body=body))
    client, http = _client(wire)
    try:
        outcome = client.orders.create(WALLET, OPERATION, _order())
        request = next(request for request in wire.requests if request.url.path.endswith("/orders"))
        assert isinstance(outcome, OrderCompleted)
        assert request.headers["Idempotency-Key"] == str(OPERATION)
        assert b'"expectedTotal":{"amount":"21.000","currency":"LYD"}' in request.content
        assert request.headers.get("Nonce")
    finally:
        client.close()
        http.close()


def test_repeated_replay_values_classify_success_as_replayed() -> None:
    """Treat comma-joined true replay values as true while preserving the signed header bytes."""
    wire = SignedMockWire(
        lambda request: WireAnswer(
            201,
            b'{"operationId":"9b2e4f17-3c6a-4d58-b0e1-7a5c8d2f6b34","status":"completed"}',
            {"Idempotency-Replayed": "true, true"},
        )
    )
    client, http = _client(wire)
    try:
        result = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(result, OrderReplayed)
    finally:
        client.close()
        http.close()


def test_repeated_replay_values_classify_refusal_as_replayed() -> None:
    """Treat repeated replay marker values on a signed refusal as an already-decided operation."""
    wire = SignedMockWire(
        lambda request: WireAnswer(
            409,
            b'{"type":"about:blank","title":"busy","status":409,"code":"dependency_unavailable"}',
            {"Idempotency-Replayed": "true, true"},
        )
    )
    client, http = _client(wire)
    try:
        result = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(result, OrderNotPlaced)
        assert result.refusal.is_replayed
    finally:
        client.close()
        http.close()


def test_encoded_signed_response_is_discarded_before_parsing() -> None:
    """Discard gzip-encoded response content because decoded HTTP bytes cannot match Anis's digest."""
    wire = SignedMockWire(
        lambda request: WireAnswer(
            200,
            gzip.compress(
                b'{"partner":{"id":"7c9e6679-7425-40de-944b-e07fc1f90ae7"},"application":{"id":"16fd2706-8baf-433b-82eb-8c7fada847da","scopes":[]}}'
            ),
            {"Content-Encoding": "gzip"},
        )
    )
    client, http = _client(wire)
    try:
        with pytest.raises(UnverifiableResponseError) as caught:
            client.profile.get()
        assert caught.value.failure.value == "content_digest_mismatch"
    finally:
        client.close()
        http.close()


def test_redirect_from_injected_follow_redirects_client_is_not_followed() -> None:
    """A signed 302 remains the answer even when the injected HTTPX client normally follows redirects."""
    wire = SignedMockWire(lambda request: WireAnswer(302, b'{"type":"about:blank","title":"redirect","status":302}'))
    http = cast(httpx.Client, wire.client())
    http.follow_redirects = True
    client = AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http)
    try:
        with pytest.raises(AnisApiError):
            client.profile.get()
        api_paths = [
            request.url.path
            for request in wire.requests
            if request.url.path != "/.well-known/partner-signing-keys.json"
        ]
        assert api_paths == ["/v1/profile"]
    finally:
        client.close()
        http.close()


def test_processing_and_replay_are_distinct_order_outcomes() -> None:
    """Interpret 202 and the signed replay marker as separate same-id recovery outcomes."""
    responses = [
        WireAnswer(
            202,
            b'{"operationId":"9b2e4f17-3c6a-4d58-b0e1-7a5c8d2f6b34","status":"processing"}',
            {"Retry-After": "9", "Location": "/v1/orders/x"},
        ),
        WireAnswer(
            201,
            b'{"operationId":"9b2e4f17-3c6a-4d58-b0e1-7a5c8d2f6b34","status":"completed"}',
            {"Idempotency-Replayed": "true"},
        ),
    ]
    wire = SignedMockWire(lambda request: responses.pop(0))
    client, http = _client(wire)
    try:
        processing = client.orders.create(WALLET, OPERATION, _order())
        replayed = client.orders.resume(WALLET, OPERATION, _order())
        assert isinstance(processing, OrderProcessing)
        assert processing.retry_after == timedelta(seconds=9)
        assert processing.location == "/v1/orders/x"
        assert isinstance(replayed, OrderReplayed)
        assert replayed.order.sold_cards is None
    finally:
        client.close()
        http.close()


def test_typed_refusal_is_verified_before_it_becomes_not_placed() -> None:
    """Raise typed API refusal data only after the problem body and replay metadata verify."""
    wire = SignedMockWire(
        lambda request: WireAnswer(
            409, b'{"type":"about:blank","title":"t","status":409,"code":"insufficient_balance"}'
        )
    )
    client, http = _client(wire)
    try:
        outcome = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(outcome, OrderNotPlaced)
        assert isinstance(outcome.refusal, InsufficientBalanceError)
        assert outcome.refusal.code.value == "insufficient_balance"
    finally:
        client.close()
        http.close()


def test_price_change_refusal_is_final_on_a_fresh_create() -> None:
    """Require a new priced intent after a fresh final price refusal instead of leaving it open for retry."""
    wire = SignedMockWire(
        lambda request: WireAnswer(409, b'{"type":"about:blank","title":"changed","status":409,"code":"price_changed"}')
    )
    client, http = _client(wire)
    try:
        result = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(result, OrderNotPlaced)
        assert isinstance(result.refusal, PriceChangedError)
    finally:
        client.close()
        http.close()


def test_nonpositive_price_is_rejected_before_any_request() -> None:
    """Reject zero or negative unit prices locally because the gateway requires a positive price."""
    wire = SignedMockWire()
    client, http = _client(wire)
    try:
        with pytest.raises(ValueError, match="greater than zero"):
            client.orders.create(WALLET, OPERATION, _order("-0.001", "-0.002"))
        assert wire.requests == []
    finally:
        client.close()
        http.close()


def test_mismatched_order_total_is_rejected_before_any_request() -> None:
    """Avoid a paid HTTP round trip when exact unit-price multiplication does not match the total."""
    wire = SignedMockWire()
    client, http = _client(wire)
    try:
        with pytest.raises(ValueError, match="ExpectedTotal"):
            client.orders.create(WALLET, OPERATION, _order(total="20.000"))
        assert wire.requests == []
    finally:
        client.close()
        http.close()


def test_transport_failure_leaves_order_unknown_with_original_cause() -> None:
    """Keep network failures open for same-id recovery because Anis may have completed the sale."""

    def fail(request: httpx.Request) -> WireAnswer:
        raise httpx.ConnectError("connection reset", request=request)

    wire = SignedMockWire(fail)
    client, http = _client(wire)
    try:
        outcome = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(outcome, OrderOutcomeUnknown)
        assert isinstance(outcome.cause, httpx.ConnectError)
        assert outcome.suggested_delay == timedelta(seconds=5)
    finally:
        client.close()
        http.close()


def test_create_does_not_retry_a_lost_answer_and_a_caller_retry_gets_a_fresh_nonce() -> None:
    """Keep retries with the caller so each attempt signs the same id with one fresh nonce."""
    answers: list[WireAnswer | httpx.ConnectError] = [
        httpx.ConnectError("connection reset"),
        WireAnswer(201, b'{"status":"completed"}'),
    ]

    def respond(request: httpx.Request) -> WireAnswer:
        answer = answers.pop(0)
        if isinstance(answer, httpx.ConnectError):
            raise answer
        return answer

    wire = SignedMockWire(respond)
    client, http = _client(wire)
    try:
        first = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(first, OrderOutcomeUnknown)
        assert len([item for item in wire.requests if item.url.path.endswith("/orders")]) == 1
        second = client.orders.resume(WALLET, OPERATION, _order())
        assert isinstance(second, OrderCompleted)
        attempts = [item for item in wire.requests if item.url.path.endswith("/orders")]
        assert len(attempts) == 2
        assert attempts[0].headers["Idempotency-Key"] == attempts[1].headers["Idempotency-Key"]
        assert attempts[0].headers["Nonce"] != attempts[1].headers["Nonce"]
        assert all(len(item.headers.get_list("Signature-Input")) == 1 for item in attempts)
    finally:
        client.close()
        http.close()


def test_empty_verified_success_leaves_order_unknown() -> None:
    """Treat a signed empty success as unusable because it cannot establish whether the order completed."""
    wire = SignedMockWire(lambda request: WireAnswer(201, b""))
    client, http = _client(wire)
    try:
        result = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(result, OrderOutcomeUnknown)
        assert isinstance(result.cause, AnisApiError)
        assert result.cause.problem.title == "Empty body"
    finally:
        client.close()
        http.close()


def test_invalid_verified_order_json_leaves_order_unknown() -> None:
    """Keep malformed success answers open for same-id recovery instead of inventing an order state."""
    wire = SignedMockWire(lambda request: WireAnswer(201, b"not-json"))
    client, http = _client(wire)
    try:
        result = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(result, OrderOutcomeUnknown)
        assert isinstance(result.cause, ValueError)
    finally:
        client.close()
        http.close()


def test_resume_refusal_without_replay_marker_remains_unknown() -> None:
    """A refusal after a prior attempt cannot close the operation unless Anis marks it replayed."""
    wire = SignedMockWire(
        lambda request: WireAnswer(409, b'{"type":"about:blank","title":"no","status":409,"code":"price_changed"}')
    )
    client, http = _client(wire)
    try:
        result = client.orders.resume(WALLET, OPERATION, _order())
        assert isinstance(result, OrderOutcomeUnknown)
        assert isinstance(result.cause, PriceChangedError)
    finally:
        client.close()
        http.close()


def test_processing_uses_five_second_default_without_retry_after() -> None:
    """Give the caller a bounded recovery delay when a processing answer omits Retry-After."""
    wire = SignedMockWire(lambda request: WireAnswer(202, b'{"status":"processing"}'))
    client, http = _client(wire)
    try:
        result = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(result, OrderProcessing)
        assert result.retry_after == timedelta(seconds=5)
    finally:
        client.close()
        http.close()


def test_create_refusal_at_access_boundary_suggests_one_minute() -> None:
    """Keep access failures open briefly because policy propagation can lag the first signed request."""
    wire = SignedMockWire(
        lambda request: WireAnswer(
            401, b'{"type":"about:blank","title":"no","status":401,"code":"invalid_credentials"}'
        )
    )
    client, http = _client(wire)
    try:
        result = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(result, OrderOutcomeUnknown)
        assert result.suggested_delay == timedelta(seconds=60)
    finally:
        client.close()
        http.close()


def test_success_credentials_win_over_a_replayed_marker() -> None:
    """Return credentials from a recovered completion even when Anis also marks the answer replayed."""
    wire = SignedMockWire(
        lambda request: WireAnswer(
            201,
            b'{"status":"completed","soldCards":[{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"V"}]}',
            {"Idempotency-Replayed": "true"},
        )
    )
    client, http = _client(wire)
    try:
        result = client.orders.resume(WALLET, OPERATION, _order())
        assert isinstance(result, OrderCompleted)
        assert result.credentials[0].voucher == "V"
    finally:
        client.close()
        http.close()


def test_completion_without_credentials_is_withheld() -> None:
    """Expose a successful order without credentials as withheld instead of prompting a duplicate purchase."""
    wire = SignedMockWire(lambda request: WireAnswer(201, b'{"status":"completed","externalReference":"ref"}'))
    client, http = _client(wire)
    try:
        result = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(result, OrderCompleted)
        assert result.codes_withheld
        assert result.credentials == ()
        assert result.order.external_reference == "ref"
    finally:
        client.close()
        http.close()


def test_completion_withheld_flag_is_preserved_without_credentials() -> None:
    """Preserve Anis's explicit withheld result because credential release may require a later reveal call."""
    wire = SignedMockWire(lambda request: WireAnswer(201, b'{"status":"completed","codesWithheld":true}'))
    client, http = _client(wire)
    try:
        result = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(result, OrderCompleted)
        assert result.codes_withheld
        assert result.order.codes_withheld is True
    finally:
        client.close()
        http.close()


def test_completed_credentials_are_not_withheld_without_a_flag() -> None:
    """Make an unflagged credential-bearing completion available for immediate fulfilment."""
    wire = SignedMockWire(
        lambda request: WireAnswer(
            201,
            b'{"status":"completed","soldCards":[{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"V"}]}',
        )
    )
    client, http = _client(wire)
    try:
        result = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(result, OrderCompleted)
        assert not result.codes_withheld
        assert result.credentials[0].voucher == "V"
    finally:
        client.close()
        http.close()


def test_rate_limited_create_uses_the_signed_retry_after() -> None:
    """Use the verified server delay for recovery so callers do not retry a limited operation too early."""
    wire = SignedMockWire(
        lambda request: WireAnswer(
            429,
            b'{"type":"about:blank","title":"slow","status":429,"code":"rate_limited"}',
            {"Retry-After": "17"},
        )
    )
    client, http = _client(wire)
    try:
        result = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(result, OrderOutcomeUnknown)
        assert result.suggested_delay == timedelta(seconds=17)
        assert isinstance(result.cause, RateLimitedError)
        assert result.cause.retry_after == timedelta(seconds=17)
    finally:
        client.close()
        http.close()


def test_rate_limited_create_without_retry_after_uses_five_seconds() -> None:
    """Use the same bounded five-second recovery delay when a rate refusal gives no explicit wait."""
    wire = SignedMockWire(
        lambda request: WireAnswer(429, b'{"type":"about:blank","title":"slow","status":429,"code":"rate_limited"}')
    )
    client, http = _client(wire)
    try:
        result = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(result, OrderOutcomeUnknown)
        assert result.suggested_delay == timedelta(seconds=5)
    finally:
        client.close()
        http.close()


def test_dependency_refusal_keeps_the_order_open_for_resume() -> None:
    """Keep dependency refusals uncertain because Anis may have accepted the order before failing downstream."""
    wire = SignedMockWire(
        lambda request: WireAnswer(
            503,
            b'{"type":"about:blank","title":"unavailable","status":503,"code":"dependency_unavailable"}',
        )
    )
    client, http = _client(wire)
    try:
        result = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(result, OrderOutcomeUnknown)
        assert result.suggested_delay == timedelta(seconds=5)
    finally:
        client.close()
        http.close()


def test_door_refusal_retry_after_overrides_the_one_minute_default() -> None:
    """Prefer a signed access-delay value when present because the gateway knows its own policy propagation window."""
    wire = SignedMockWire(
        lambda request: WireAnswer(
            401,
            b'{"type":"about:blank","title":"no","status":401,"code":"invalid_credentials"}',
            {"Retry-After": "8"},
        )
    )
    client, http = _client(wire)
    try:
        result = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(result, OrderOutcomeUnknown)
        assert result.suggested_delay == timedelta(seconds=8)
    finally:
        client.close()
        http.close()


def test_resume_door_refusal_without_retry_after_suggests_one_minute() -> None:
    """Keep an access refusal on resume open for the same operation id while allowing policy to converge."""
    wire = SignedMockWire(
        lambda request: WireAnswer(
            401, b'{"type":"about:blank","title":"no","status":401,"code":"invalid_credentials"}'
        )
    )
    client, http = _client(wire)
    try:
        result = client.orders.resume(WALLET, OPERATION, _order())
        assert isinstance(result, OrderOutcomeUnknown)
        assert result.suggested_delay == timedelta(seconds=60)
    finally:
        client.close()
        http.close()


def test_timeout_on_create_and_resume_keeps_the_operation_unknown() -> None:
    """Keep either unanswered attempt open because the server may have accepted either create."""

    def timeout(request: httpx.Request) -> WireAnswer:
        raise httpx.ReadTimeout("response timed out", request=request)

    wire = SignedMockWire(timeout)
    client, http = _client(wire)
    try:
        created = client.orders.create(WALLET, OPERATION, _order())
        resumed = client.orders.resume(WALLET, OPERATION, _order())
        assert isinstance(created, OrderOutcomeUnknown)
        assert isinstance(created.cause, httpx.ReadTimeout)
        assert isinstance(resumed, OrderOutcomeUnknown)
        assert isinstance(resumed.cause, httpx.ReadTimeout)
    finally:
        client.close()
        http.close()


def test_unexpected_send_failure_leaves_order_unknown() -> None:
    """Keep the operation open when an injected transport fails outside HTTPX's normal network exceptions."""

    def fail(request: httpx.Request) -> WireAnswer:
        raise RuntimeError("host transport failure")

    wire = SignedMockWire(fail)
    client, http = _client(wire)
    try:
        result = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(result, OrderOutcomeUnknown)
        assert isinstance(result.cause, RuntimeError)
        assert str(result.cause) == "host transport failure"
    finally:
        client.close()
        http.close()


def test_injected_sync_client_remains_open_after_sdk_close() -> None:
    """Leave injected connections to their host because another component may still be using them."""
    wire = SignedMockWire()
    http = cast(httpx.Client, wire.client())
    client = AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http)
    client.close()
    assert not http.is_closed
    http.close()


def test_sdk_created_sync_client_closes_with_its_context_manager() -> None:
    """Release internally owned connections when the client leaves its context."""
    client = AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER)
    http = client._http
    with client:
        assert not http.is_closed
    assert http.is_closed


def test_host_clock_and_nonce_factory_are_used_for_signed_requests() -> None:
    """Keep host time and nonce policy authoritative so signatures match host test and runtime controls."""

    class FixedClock:
        value = datetime.now(UTC)

        def now(self) -> datetime:
            return self.value

    class FixedNonce:
        def create(self) -> str:
            return "host-nonce-value"

    wire = SignedMockWire()
    http = cast(httpx.Client, wire.client())
    client = AnisPartnersClient(
        ClientOptions("https://partners.test"), SIGNER, http_client=http, clock=FixedClock(), nonce_factory=FixedNonce()
    )
    try:
        client.owned_cards.reveal(WALLET, CARD_SOLD)
        request = next(item for item in wire.requests if item.url.path.endswith("/reveal"))
        assert request.headers["X-Anis-Date"] == FixedClock.value.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert request.headers["Nonce"] == "host-nonce-value"
    finally:
        client.close()
        http.close()


def test_signer_failure_propagates_without_sending_or_counting_unknown() -> None:
    """Report signer custody failures directly because nothing was sent and no purchase became uncertain."""

    class FailingSigner:
        key_id = "9e96dc41-c715-4cc4-b1aa-836fe42ad0bb"

        def sign(self, data: bytes) -> bytes:
            raise OSError("vault unavailable")

    wire = SignedMockWire()
    http = cast(httpx.Client, wire.client())
    client = AnisPartnersClient(
        ClientOptions("https://partners.test"), cast(RequestSigner, FailingSigner()), http_client=http
    )
    try:
        with pytest.raises(RequestSigningError) as failure:
            client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(failure.value.__cause__, OSError)
        assert "vault unavailable" not in str(failure.value)
        assert wire.requests == []
    finally:
        client.close()
        http.close()


def test_replayed_refusal_is_not_placed() -> None:
    """Treat a marked replay refusal as a known no-sale even for an otherwise uncertain code."""
    wire = SignedMockWire(
        lambda request: WireAnswer(
            409,
            b'{"type":"about:blank","title":"recorded","status":409,"code":"dependency_unavailable"}',
            {"Idempotency-Replayed": "true"},
        )
    )
    client, http = _client(wire)
    try:
        result = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(result, OrderNotPlaced)
        assert result.refusal.is_replayed
    finally:
        client.close()
        http.close()


def test_replayed_door_refusal_is_not_placed() -> None:
    """Treat a recorded access refusal as known not-placed so a caller does not keep an old purchase open."""
    wire = SignedMockWire(
        lambda request: WireAnswer(
            401,
            b'{"type":"about:blank","title":"no","status":401,"code":"invalid_credentials"}',
            {"Idempotency-Replayed": "true"},
        )
    )
    client, http = _client(wire)
    try:
        result = client.orders.create(WALLET, OPERATION, _order())
        assert isinstance(result, OrderNotPlaced)
        assert result.refusal.is_replayed
    finally:
        client.close()
        http.close()


@pytest.mark.anyio
async def test_injected_async_client_remains_open_after_sdk_close() -> None:
    """Leave async connections host-owned when the SDK closes its wrapper."""
    wire = SignedMockWire()
    http = cast(httpx.AsyncClient, wire.client(async_client=True))
    client = AsyncAnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http)
    await client.aclose()
    assert not http.is_closed
    await http.aclose()


@pytest.mark.anyio
async def test_sdk_created_async_client_closes_with_its_context_manager() -> None:
    """Release internally created async connections on context exit."""
    client = AsyncAnisPartnersClient(ClientOptions("https://partners.test"), SIGNER)
    http = client._http
    async with client:
        assert not http.is_closed
    assert http.is_closed


@pytest.mark.anyio
async def test_async_wallet_iteration_follows_cursor_pages() -> None:
    """Yield all pages in sequence so a normal list operation cannot truncate eligible wallets."""
    answers = [
        WireAnswer(
            body=b'{"items":[{"id":"11111111-1111-1111-1111-111111111111","name":"A","currency":"LYD","balance":{"amount":"1.000","currency":"LYD"}}],"nextCursor":"next"}'
        ),
        WireAnswer(
            body=b'{"items":[{"id":"22222222-2222-2222-2222-222222222222","name":"B","currency":"LYD","balance":{"amount":"2.000","currency":"LYD"}}],"nextCursor":null}'
        ),
    ]
    wire = SignedMockWire(lambda request: answers.pop(0))
    http = cast(httpx.AsyncClient, wire.client(async_client=True))
    async with AsyncAnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http) as client:
        names = [item.name async for item in client.wallets.list()]
        assert names == ["A", "B"]
        requests = [item for item in wire.requests if item.url.path == "/v1/wallets"]
        assert len(requests) == 2
        assert requests[0].url.query == b""
        assert requests[1].url.query == b"cursor=next"
    await http.aclose()


def test_owned_cards_iterate_all_cursor_pages() -> None:
    """Follow every owned-card cursor so a first page cannot masquerade as the full wallet state."""
    answers = [
        WireAnswer(body=b'{"items":[{"id":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046"}],"nextCursor":"next"}'),
        WireAnswer(body=b'{"items":[{"id":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046"}],"nextCursor":null}'),
    ]
    wire = SignedMockWire(lambda request: answers.pop(0))
    client, http = _client(wire)
    try:
        cards = list(client.owned_cards.list(WALLET))
        assert len(cards) == 2
        requests = [item for item in wire.requests if item.url.path.endswith("/cards")]
        assert len(requests) == 2
        assert requests[1].url.query == b"cursor=next"
    finally:
        client.close()
        http.close()


def test_catalogue_cards_iterate_all_cursor_pages() -> None:
    """Follow catalogue card cursors so availability and pricing remain complete across pages."""
    answers = [
        WireAnswer(body=b'{"items":[],"nextCursor":"next"}'),
        WireAnswer(body=b'{"items":[],"nextCursor":null}'),
    ]
    wire = SignedMockWire(lambda request: answers.pop(0))
    client, http = _client(wire)
    try:
        assert list(client.catalogue.list_cards(WALLET, CARD)) == []
        requests = [item for item in wire.requests if item.url.path.endswith("/cards")]
        assert len(requests) == 2
        assert requests[1].url.query == b"cursor=next"
    finally:
        client.close()
        http.close()


def test_catalogue_categories_and_subcategories_iterate_all_cursor_pages() -> None:
    """Follow category and subcategory cursors so later purchase guidance remains visible."""
    responses: dict[str, list[WireAnswer]] = {
        "/catalog/categories": [
            WireAnswer(body=b'{"items":[],"nextCursor":"next"}'),
            WireAnswer(body=b'{"items":[],"nextCursor":null}'),
        ],
        "/subcategories": [
            WireAnswer(body=b'{"items":[],"nextCursor":"next"}'),
            WireAnswer(body=b'{"items":[],"nextCursor":null}'),
        ],
    }

    def answer(request: httpx.Request) -> WireAnswer:
        suffix = "/subcategories" if request.url.path.endswith("/subcategories") else "/catalog/categories"
        return responses[suffix].pop(0)

    wire = SignedMockWire(answer)
    client, http = _client(wire)
    try:
        assert list(client.catalogue.list_categories(WALLET)) == []
        assert list(client.catalogue.list_subcategories(WALLET, CARD)) == []
        assert len([item for item in wire.requests if item.url.path.endswith("/catalog/categories")]) == 2
        assert len([item for item in wire.requests if item.url.path.endswith("/subcategories")]) == 2
    finally:
        client.close()
        http.close()


@pytest.mark.anyio
async def test_async_cancellation_propagates_after_counting_the_order_unknown(caplog: pytest.LogCaptureFixture) -> None:
    """Rethrow caller cancellation after recording unknown because the server may still place the order."""

    def cancel(request: httpx.Request) -> WireAnswer:
        raise asyncio.CancelledError()

    wire = SignedMockWire(cancel)
    http = cast(httpx.AsyncClient, wire.client(async_client=True))
    client = AsyncAnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http)
    caplog.set_level(logging.DEBUG, logger="anis_partners")
    with pytest.raises(asyncio.CancelledError):
        await client.orders.create(WALLET, OPERATION, _order())
    assert any(getattr(record, "event_id", None) == 1008 for record in caplog.records)
    await http.aclose()


def test_client_uses_a_route_template_in_safe_structured_logs(caplog: pytest.LogCaptureFixture) -> None:
    """Log stable route templates and event ids so concrete wallet ids do not become telemetry dimensions."""
    wire = SignedMockWire(
        lambda request: WireAnswer(
            body=b'{"id":"2f1c8a94-6d37-4e52-b8a1-0c9e5d3f7b26","name":"Main","currency":"LYD","balance":{"amount":"1.000","currency":"LYD"}}'
        )
    )
    client, http = _client(wire)
    caplog.set_level(logging.DEBUG, logger="anis_partners")
    try:
        client.wallets.get(WALLET)
        assert any(getattr(record, "event_id", None) == 1000 for record in caplog.records)
        assert any(getattr(record, "event_id", None) == 1001 for record in caplog.records)
        assert all(str(WALLET) not in record.getMessage() for record in caplog.records)
    finally:
        client.close()
        http.close()


@pytest.fixture
def anyio_backend() -> str:
    """Use asyncio so cancellation tests match the supported async runtime."""
    return "asyncio"
