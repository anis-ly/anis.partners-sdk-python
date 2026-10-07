"""Exercise public sync and async clients through a signed in-memory HTTPX wire."""

from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import inspect
import logging
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import httpx
import pytest

from anis_partners import (
    AnisApiError,
    AnisPartnersClient,
    AsyncAnisPartnersClient,
    ClientOptions,
    CreateOrderRequest,
    InsufficientBalanceError,
    MalformedResponseError,
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
from anis_partners.operations.groups import AsyncOrderOperations, SyncOrderOperations
from anis_partners.operations.transport import RequestSpec
from anis_partners.signing.errors import RequestSigningError
from anis_partners.signing.signature_profile import SignatureProfile
from tests.support.partner import CARD, CARD_SOLD, OPERATION, SIGNER, WALLET
from tests.support.partner import order as _order
from tests.support.sdk_wire import SignedMockWire, WireAnswer


def _client(wire: SignedMockWire) -> tuple[AnisPartnersClient, httpx.Client]:
    http = cast(httpx.Client, wire.client())
    return AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http), http


def test_order_wallet_operation_and_request_must_be_named_arguments() -> None:
    """Prevent swapped UUID arguments from becoming a plausible but misaddressed purchase."""
    for sync_operation in (SyncOrderOperations.create, SyncOrderOperations.resume):
        parameters = inspect.signature(sync_operation).parameters
        for name in ("wallet_id", "operation_id", "order"):
            assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
    for async_operation in (AsyncOrderOperations.create, AsyncOrderOperations.resume):
        parameters = inspect.signature(async_operation).parameters
        for name in ("wallet_id", "operation_id", "order"):
            assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY


def test_request_core_refuses_an_escaped_path_before_http_send() -> None:
    """Reject escaped paths before HTTPX could sign a different route from the decoded gateway path."""
    wire = SignedMockWire()
    client, http = _client(wire)
    try:
        spec = RequestSpec("GET", "/v1/profile", "/v1/profile%2Fextra", SignatureProfile.SAFE_READ)
        with pytest.raises(RequestSigningError):
            client.profile._transport.send(spec, lambda data: data)
        assert wire.requests == []
    finally:
        client.close()
        http.close()


def test_sync_profile_request_is_signed_and_its_unsigned_answer_is_read() -> None:
    """Sign the safe read as before; the profile answer is unsigned, so no response key is fetched."""
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
        assert wire.key_document_requests == 0
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


def test_tampered_order_answer_with_matching_digest_fails_signature_verification() -> None:
    """Check transport handling after a valid digest isolates tampering to the response signature."""
    wire = SignedMockWire(
        lambda request: WireAnswer(
            201,
            b'{"status":"completed","soldCards":[{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"V"}]}',
        )
    )

    def alter(request: httpx.Request) -> httpx.Response:
        response = wire.handle(request)
        if request.url.path == "/.well-known/partner-signing-keys.json":
            return response
        body = b'{"status":"completed","soldCards":[{"voucher":"tampered"}]}'
        headers = dict(response.headers)
        headers["content-digest"] = "sha-256=:" + base64.b64encode(hashlib.sha256(body).digest()).decode() + ":"
        return httpx.Response(response.status_code, headers=headers, content=body, request=request)

    http = httpx.Client(transport=httpx.MockTransport(alter))
    client = AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http)
    try:
        outcome = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
        assert isinstance(outcome, OrderOutcomeUnknown)
        assert isinstance(outcome.cause, UnverifiableResponseError)
        assert outcome.cause.failure.value == "signature_invalid"
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
        outcome = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
        assert isinstance(result, OrderNotPlaced)
        assert isinstance(result.refusal, AnisApiError)
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
                b'{"routeId":"signature-diagnostic","method":"POST","coveredComponents":[],"effectiveScopes":[]}'
            ),
            {"Content-Encoding": "gzip"},
        )
    )
    client, http = _client(wire)
    try:
        with pytest.raises(UnverifiableResponseError) as caught:
            client.diagnostics.check_signature()
        assert caught.value.failure.value == "content_digest_mismatch"
    finally:
        client.close()
        http.close()


def test_redirect_from_injected_follow_redirects_client_is_not_followed() -> None:
    """A 302 remains the answer even when the injected HTTPX client normally follows redirects."""
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
        processing = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
        replayed = client.orders.resume(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
        outcome = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
        with pytest.raises(ValueError, match="expected_unit_price"):
            client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order("-0.001", "-0.002"))
        assert wire.requests == []
    finally:
        client.close()
        http.close()


def test_mismatched_order_total_is_rejected_before_any_request() -> None:
    """Avoid a paid HTTP round trip when exact unit-price multiplication does not match the total."""
    wire = SignedMockWire()
    client, http = _client(wire)
    try:
        with pytest.raises(ValueError, match="expected_total"):
            client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order(total="20.000"))
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
        outcome = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
        first = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
        assert isinstance(first, OrderOutcomeUnknown)
        assert len([item for item in wire.requests if item.url.path.endswith("/orders")]) == 1
        second = client.orders.resume(wallet_id=WALLET, operation_id=OPERATION, order=_order())
        assert isinstance(second, OrderCompleted)
        attempts = [item for item in wire.requests if item.url.path.endswith("/orders")]
        assert len(attempts) == 2
        assert attempts[0].headers["Idempotency-Key"] == attempts[1].headers["Idempotency-Key"]
        assert attempts[0].headers["Nonce"] != attempts[1].headers["Nonce"]
        assert all(len(item.headers.get_list("Signature-Input")) == 1 for item in attempts)
    finally:
        client.close()
        http.close()


def test_empty_verified_success_leaves_order_unknown_without_a_refusal_event(caplog: pytest.LogCaptureFixture) -> None:
    """Treat a signed empty success as unusable because it cannot establish whether the order completed."""
    wire = SignedMockWire(lambda request: WireAnswer(201, b""))
    client, http = _client(wire)
    caplog.set_level(logging.DEBUG, logger="anis_partners")
    try:
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
        assert isinstance(result, OrderOutcomeUnknown)
        assert isinstance(result.cause, MalformedResponseError)
        assert not any(getattr(record, "event_id", None) == 1002 for record in caplog.records)
    finally:
        client.close()
        http.close()


def test_invalid_verified_order_json_leaves_order_unknown() -> None:
    """Keep malformed success answers open for same-id recovery instead of inventing an order state."""
    wire = SignedMockWire(lambda request: WireAnswer(201, b"not-json"))
    client, http = _client(wire)
    try:
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
        assert isinstance(result, OrderOutcomeUnknown)
        from anis_partners.errors import MalformedResponseError

        assert isinstance(result.cause, MalformedResponseError)
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
        result = client.orders.resume(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
        result = client.orders.resume(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
        result = client.orders.resume(wallet_id=WALLET, operation_id=OPERATION, order=_order())
        assert isinstance(result, OrderOutcomeUnknown)
        assert result.suggested_delay == timedelta(seconds=60)
    finally:
        client.close()
        http.close()


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("invalid_credentials", 401),
        ("signature_expired", 401),
        ("insufficient_scope", 403),
        ("wallet_not_granted", 404),
        ("malformed_signed_request", 400),
    ],
)
@pytest.mark.parametrize("operation", ["create", "resume"])
def test_sync_door_refusals_keep_create_and_resume_unknown(code: str, status: int, operation: str) -> None:
    """Keep every access-boundary refusal open because an earlier request may already have placed the order."""
    wire = SignedMockWire(lambda request: WireAnswer(status, f'{{"code":"{code}"}}'.encode()))
    client, http = _client(wire)
    try:
        outcome = getattr(client.orders, operation)(wallet_id=WALLET, operation_id=OPERATION, order=_order())
        assert isinstance(outcome, OrderOutcomeUnknown)
        assert outcome.suggested_delay == timedelta(seconds=60)
        assert isinstance(outcome.cause, AnisApiError)
        assert outcome.cause.raw_code == code
        assert len([item for item in wire.requests if item.url.path.endswith("/orders")]) == 1
    finally:
        client.close()
        http.close()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("invalid_credentials", 401),
        ("signature_expired", 401),
        ("insufficient_scope", 403),
        ("wallet_not_granted", 404),
        ("malformed_signed_request", 400),
    ],
)
@pytest.mark.parametrize("operation", ["create", "resume"])
async def test_async_door_refusals_keep_create_and_resume_unknown(code: str, status: int, operation: str) -> None:
    """Apply the same one-minute recovery rule to both async order entry points."""
    wire = SignedMockWire(lambda request: WireAnswer(status, f'{{"code":"{code}"}}'.encode()))
    http = cast(httpx.AsyncClient, wire.client(async_client=True))
    client = AsyncAnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http)
    try:
        outcome = await getattr(client.orders, operation)(wallet_id=WALLET, operation_id=OPERATION, order=_order())
        assert isinstance(outcome, OrderOutcomeUnknown)
        assert outcome.suggested_delay == timedelta(seconds=60)
        assert isinstance(outcome.cause, AnisApiError)
        assert outcome.cause.raw_code == code
        assert len([item for item in wire.requests if item.url.path.endswith("/orders")]) == 1
    finally:
        await client.aclose()
        await http.aclose()


def _invalid_order(kind: str) -> CreateOrderRequest:
    unit = Money(Decimal("10.500"), "LYD")
    total = Money(Decimal("21.000"), "LYD")
    quantity = 2
    if kind == "quantity":
        quantity, total = 0, Money(Decimal("0.000"), "LYD")
    elif kind == "unit-price":
        unit, total = Money(Decimal("0.000"), "LYD"), Money(Decimal("0.000"), "LYD")
    elif kind == "currency":
        unit = Money(Decimal("10.500"), "USD")
    elif kind == "total":
        total = Money(Decimal("30.000"), "LYD")
    return CreateOrderRequest(CARD, quantity, unit, total)


@pytest.mark.parametrize(
    ("kind", "argument"),
    [
        ("quantity", "quantity"),
        ("unit-price", "expected_unit_price"),
        ("currency", "expected_total currency"),
        ("total", "expected_total"),
    ],
)
@pytest.mark.parametrize("operation", ["create", "resume"])
def test_sync_order_preflight_guards_run_before_both_order_calls(kind: str, argument: str, operation: str) -> None:
    """Refuse invalid purchase arithmetic locally on both paths so no bad request can reach Anis."""
    wire = SignedMockWire(lambda request: WireAnswer(status=201, body=b'{"status":"completed"}'))
    client, http = _client(wire)
    try:
        with pytest.raises(ValueError, match=argument):
            getattr(client.orders, operation)(wallet_id=WALLET, operation_id=OPERATION, order=_invalid_order(kind))
        assert wire.requests == []
    finally:
        client.close()
        http.close()


@pytest.mark.parametrize("mode", ["throw-get", "throw-set", "garbage", "hanging"])
def test_sync_order_credentials_survive_key_cache_faults(mode: str) -> None:
    """Keep verified sold-card codes when the optional sync key cache fails or responds slowly."""

    class FaultyCache:
        def get(self, key: str) -> str | None:
            if mode == "throw-get":
                raise ConnectionError("cache get failed")
            if mode == "garbage":
                return "not a key document"
            if mode == "hanging":
                time.sleep(0.03)
            return None

        def set(self, key: str, value: str, ttl_seconds: int) -> None:
            if mode == "throw-set":
                raise ConnectionError("cache set failed")
            if mode == "hanging":
                time.sleep(0.03)

    wire = SignedMockWire(
        lambda request: WireAnswer(
            201,
            b'{"status":"completed","soldCards":[{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","serialNumber":"serial-42","voucher":"voucher-42"}]}',
        )
    )
    http = cast(httpx.Client, wire.client())
    client = AnisPartnersClient(
        ClientOptions("https://partners.test"), SIGNER, http_client=http, key_cache=FaultyCache()
    )
    try:
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
        assert isinstance(result, OrderCompleted)
        assert result.credentials[0].serial_number == "serial-42"
        assert result.credentials[0].voucher == "voucher-42"
    finally:
        client.close()
        http.close()


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["throw-get", "throw-set", "garbage", "hanging"])
async def test_async_order_credentials_survive_key_cache_faults(mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep verified sold-card codes when the async client's shared-cache hook fails or never responds."""
    import anis_partners._internal.key_document_cache as cache_module

    if mode == "hanging":
        monkeypatch.setattr(cache_module, "ASYNC_CACHE_TIMEOUT_SECONDS", 0.02)

    class FaultyCache:
        async def get(self, key: str) -> str | None:
            if mode == "throw-get":
                raise ConnectionError("cache get failed")
            if mode == "garbage":
                return "not a key document"
            if mode == "hanging":
                await asyncio.Event().wait()
            return None

        async def set(self, key: str, value: str, ttl_seconds: int) -> None:
            if mode == "throw-set":
                raise ConnectionError("cache set failed")
            if mode == "hanging":
                await asyncio.Event().wait()

    wire = SignedMockWire(
        lambda request: WireAnswer(
            201,
            b'{"status":"completed","soldCards":[{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","serialNumber":"serial-42","voucher":"voucher-42"}]}',
        )
    )
    http = cast(httpx.AsyncClient, wire.client(async_client=True))
    client = AsyncAnisPartnersClient(
        ClientOptions("https://partners.test"), SIGNER, http_client=http, key_cache=FaultyCache()
    )
    try:
        result = await client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
        assert isinstance(result, OrderCompleted)
        assert result.credentials[0].serial_number == "serial-42"
        assert result.credentials[0].voucher == "voucher-42"
    finally:
        await client.aclose()
        await http.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("kind", "argument"),
    [
        ("quantity", "quantity"),
        ("unit-price", "expected_unit_price"),
        ("currency", "expected_total currency"),
        ("total", "expected_total"),
    ],
)
@pytest.mark.parametrize("operation", ["create", "resume"])
async def test_async_order_preflight_guards_run_before_both_order_calls(
    kind: str, argument: str, operation: str
) -> None:
    """Refuse malformed purchase intent in async create and resume before transport or key lookup."""
    wire = SignedMockWire(lambda request: WireAnswer(status=201, body=b'{"status":"completed"}'))
    http = cast(httpx.AsyncClient, wire.client(async_client=True))
    client = AsyncAnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http)
    try:
        with pytest.raises(ValueError, match=argument):
            await getattr(client.orders, operation)(
                wallet_id=WALLET, operation_id=OPERATION, order=_invalid_order(kind)
            )
        assert wire.requests == []
    finally:
        await client.aclose()
        await http.aclose()


@pytest.mark.parametrize("operation", ["create", "resume"])
def test_sync_order_argument_errors_are_direct_and_never_sent(operation: str) -> None:
    """Keep malformed order identifiers and a missing request in the caller-error path."""
    wire = SignedMockWire()
    client, http = _client(wire)
    try:
        with pytest.raises(ValueError, match="wallet_id"):
            getattr(client.orders, operation)(wallet_id="bad-id", operation_id=OPERATION, order=_order())
        with pytest.raises(ValueError, match="operation_id"):
            getattr(client.orders, operation)(wallet_id=WALLET, operation_id="bad-id", order=_order())
        with pytest.raises(TypeError, match="order"):
            getattr(client.orders, operation)(wallet_id=WALLET, operation_id=OPERATION, order=None)
        assert wire.requests == []
    finally:
        client.close()
        http.close()


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["create", "resume"])
async def test_async_order_argument_errors_are_direct_and_never_sent(operation: str) -> None:
    """Keep malformed async order arguments outside unknown-outcome and signing-error handling."""
    wire = SignedMockWire()
    http = cast(httpx.AsyncClient, wire.client(async_client=True))
    client = AsyncAnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http)
    try:
        with pytest.raises(ValueError, match="wallet_id"):
            await getattr(client.orders, operation)(wallet_id="bad-id", operation_id=OPERATION, order=_order())
        with pytest.raises(ValueError, match="operation_id"):
            await getattr(client.orders, operation)(wallet_id=WALLET, operation_id="bad-id", order=_order())
        with pytest.raises(TypeError, match="order"):
            await getattr(client.orders, operation)(wallet_id=WALLET, operation_id=OPERATION, order=None)
        assert wire.requests == []
    finally:
        await client.aclose()
        await http.aclose()


def test_timeout_on_create_and_resume_keeps_the_operation_unknown() -> None:
    """Keep either unanswered attempt open because the server may have accepted either create."""

    def timeout(request: httpx.Request) -> WireAnswer:
        raise httpx.ReadTimeout("response timed out", request=request)

    wire = SignedMockWire(timeout)
    client, http = _client(wire)
    try:
        created = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
        resumed = client.orders.resume(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
            client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
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
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
        assert isinstance(result, OrderNotPlaced)
        assert isinstance(result.refusal, AnisApiError)
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
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
        assert isinstance(result, OrderNotPlaced)
        assert isinstance(result.refusal, AnisApiError)
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


@pytest.mark.anyio
async def test_async_wallet_iteration_refuses_a_nonadjacent_cursor_cycle() -> None:
    """Stop async A-to-B-to-A paging so changing cursors cannot repeat pages indefinitely."""
    from anis_partners import MalformedResponseError

    answers = [
        WireAnswer(body=b'{"items":[],"nextCursor":"A"}'),
        WireAnswer(body=b'{"items":[],"nextCursor":"B"}'),
        WireAnswer(body=b'{"items":[],"nextCursor":"A"}'),
    ]
    wire = SignedMockWire(lambda request: answers.pop(0))
    http = cast(httpx.AsyncClient, wire.client(async_client=True))
    async with AsyncAnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http) as client:
        with pytest.raises(MalformedResponseError, match="repeated cursor"):
            [wallet async for wallet in client.wallets.list()]
        assert [request.url.query for request in wire.requests if request.url.path == "/v1/wallets"] == [
            b"",
            b"cursor=A",
            b"cursor=B",
        ]
    await http.aclose()


def test_sync_wallet_iteration_follows_cursor_pages() -> None:
    """Yield every wallet so an eligible later page is not silently omitted."""
    answers = [
        WireAnswer(
            body=b'{"items":[{"id":"11111111-1111-1111-1111-111111111111","name":"A","currency":"LYD","balance":{"amount":"1.000","currency":"LYD"}}],"nextCursor":"next"}'
        ),
        WireAnswer(
            body=b'{"items":[{"id":"22222222-2222-2222-2222-222222222222","name":"B","currency":"LYD","balance":{"amount":"2.000","currency":"LYD"}}],"nextCursor":null}'
        ),
    ]
    wire = SignedMockWire(lambda request: answers.pop(0))
    client, http = _client(wire)
    try:
        assert [wallet.name for wallet in client.wallets.list()] == ["A", "B"]
        requests = [item for item in wire.requests if item.url.path == "/v1/wallets"]
        assert len(requests) == 2
        assert requests[1].url.query == b"cursor=next"
    finally:
        client.close()
        http.close()


def test_sync_wallet_iteration_refuses_a_nonadjacent_cursor_cycle() -> None:
    """Stop A-to-B-to-A pagination because continuing would repeat pages indefinitely."""
    from anis_partners import MalformedResponseError

    answers = [
        WireAnswer(body=b'{"items":[],"nextCursor":"A"}'),
        WireAnswer(body=b'{"items":[],"nextCursor":"B"}'),
        WireAnswer(body=b'{"items":[],"nextCursor":"A"}'),
    ]
    wire = SignedMockWire(lambda request: answers.pop(0))
    client, http = _client(wire)
    try:
        with pytest.raises(MalformedResponseError, match="repeated cursor"):
            list(client.wallets.list())
        assert [request.url.query for request in wire.requests if request.url.path == "/v1/wallets"] == [
            b"",
            b"cursor=A",
            b"cursor=B",
        ]
    finally:
        client.close()
        http.close()


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
        WireAnswer(
            body=b'{"items":[{"id":"11111111-1111-1111-1111-111111111111","subcategoryId":"22222222-2222-2222-2222-222222222222","unitPrice":{"amount":"1.000","currency":"LYD"}}],"nextCursor":"next"}'
        ),
        WireAnswer(
            body=b'{"items":[{"id":"33333333-3333-3333-3333-333333333333","subcategoryId":"22222222-2222-2222-2222-222222222222","unitPrice":{"amount":"2.000","currency":"LYD"}}],"nextCursor":null}'
        ),
    ]
    wire = SignedMockWire(lambda request: answers.pop(0))
    client, http = _client(wire)
    try:
        cards = list(client.catalogue.list_cards(WALLET, CARD))
        assert [item.unit_price.amount for item in cards if item.unit_price is not None] == [
            Decimal("1.000"),
            Decimal("2.000"),
        ]
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
            WireAnswer(
                body=b'{"items":[{"id":"11111111-1111-1111-1111-111111111111","name":{"en":"A"}}],"nextCursor":"next"}'
            ),
            WireAnswer(
                body=b'{"items":[{"id":"22222222-2222-2222-2222-222222222222","name":{"en":"B"}}],"nextCursor":null}'
            ),
        ],
        "/subcategories": [
            WireAnswer(
                body=b'{"items":[{"id":"11111111-1111-1111-1111-111111111111","categoryId":"22222222-2222-2222-2222-222222222222","name":{"en":"A"}}],"nextCursor":"next"}'
            ),
            WireAnswer(
                body=b'{"items":[{"id":"33333333-3333-3333-3333-333333333333","categoryId":"22222222-2222-2222-2222-222222222222","name":{"en":"B"}}],"nextCursor":null}'
            ),
        ],
    }

    def answer(request: httpx.Request) -> WireAnswer:
        suffix = "/subcategories" if request.url.path.endswith("/subcategories") else "/catalog/categories"
        return responses[suffix].pop(0)

    wire = SignedMockWire(answer)
    client, http = _client(wire)
    try:
        assert len(list(client.catalogue.list_categories(WALLET))) == 2
        assert len(list(client.catalogue.list_subcategories(WALLET, CARD))) == 2
        categories = [item for item in wire.requests if item.url.path.endswith("/catalog/categories")]
        subcategories = [item for item in wire.requests if item.url.path.endswith("/subcategories")]
        assert len(categories) == 2
        assert categories[1].url.query == b"cursor=next"
        assert len(subcategories) == 2
        assert subcategories[1].url.query == b"cursor=next"
    finally:
        client.close()
        http.close()


@pytest.mark.anyio
async def test_async_catalogue_and_owned_card_iterators_yield_nonempty_later_pages() -> None:
    """Prove async paging returns real entries from both pages for every list endpoint."""
    pages = {
        "categories": [
            b'{"items":[{"id":"11111111-1111-1111-1111-111111111111"}],"nextCursor":"next"}',
            b'{"items":[{"id":"22222222-2222-2222-2222-222222222222"}],"nextCursor":null}',
        ],
        "subcategories": [
            b'{"items":[{"id":"11111111-1111-1111-1111-111111111111","categoryId":"22222222-2222-2222-2222-222222222222"}],"nextCursor":"next"}',
            b'{"items":[{"id":"33333333-3333-3333-3333-333333333333","categoryId":"22222222-2222-2222-2222-222222222222"}],"nextCursor":null}',
        ],
        "catalogue_cards": [
            b'{"items":[{"id":"11111111-1111-1111-1111-111111111111","subcategoryId":"22222222-2222-2222-2222-222222222222"}],"nextCursor":"next"}',
            b'{"items":[{"id":"33333333-3333-3333-3333-333333333333","subcategoryId":"22222222-2222-2222-2222-222222222222"}],"nextCursor":null}',
        ],
        "owned_cards": [
            b'{"items":[{"id":"11111111-1111-1111-1111-111111111111"}],"nextCursor":"next"}',
            b'{"items":[{"id":"33333333-3333-3333-3333-333333333333"}],"nextCursor":null}',
        ],
    }

    def answer(request: httpx.Request) -> WireAnswer:
        path = request.url.path
        key = (
            "subcategories"
            if path.endswith("/subcategories")
            else "catalogue_cards"
            if "/catalog/subcategories/" in path and path.endswith("/cards")
            else "owned_cards"
            if path.endswith("/cards")
            else "categories"
        )
        return WireAnswer(body=pages[key].pop(0))

    wire = SignedMockWire(answer)
    http = cast(httpx.AsyncClient, wire.client(async_client=True))
    async with AsyncAnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http) as client:
        categories = [item async for item in client.catalogue.list_categories(WALLET)]
        subcategories = [item async for item in client.catalogue.list_subcategories(WALLET, CARD)]
        cards = [item async for item in client.catalogue.list_cards(WALLET, CARD)]
        owned = [item async for item in client.owned_cards.list(WALLET)]
    await http.aclose()
    assert len(categories) == len(subcategories) == len(cards) == len(owned) == 2
    for endpoint in ("/catalog/categories", "/subcategories"):
        sent = [request for request in wire.requests if request.url.path.endswith(endpoint)]
        assert len(sent) == 2
        assert sent[1].url.query == b"cursor=next"
    for sent in (
        [request for request in wire.requests if "/catalog/subcategories/" in request.url.path],
        [
            request
            for request in wire.requests
            if request.url.path.endswith("/cards") and "/catalog/" not in request.url.path
        ],
    ):
        assert len(sent) == 2
        assert sent[1].url.query == b"cursor=next"


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
        await client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
    assert any(getattr(record, "event_id", None) == 1008 for record in caplog.records)
    await http.aclose()


@pytest.mark.anyio
async def test_async_client_awaits_an_async_signer() -> None:
    """Allow an asynchronous vault to sign without adapting it into synchronous code."""

    class AsyncSigner:
        key_id = SIGNER.key_id

        async def sign(self, data: bytes) -> bytes:
            await asyncio.sleep(0)
            return SIGNER.sign(data)

    wire = SignedMockWire(
        lambda request: WireAnswer(
            body=b'{"partner":{"id":"7c9e6679-7425-40de-944b-e07fc1f90ae7"},"application":{"id":"16fd2706-8baf-433b-82eb-8c7fada847da","scopes":[]}}'
        )
    )
    http = cast(httpx.AsyncClient, wire.client(async_client=True))
    async with AsyncAnisPartnersClient(
        ClientOptions("https://partners.test"), AsyncSigner(), http_client=http
    ) as client:
        profile = await client.profile.get()
    await http.aclose()
    assert profile.application is not None
    assert len([item for item in wire.requests if item.url.path == "/v1/profile"]) == 1


@pytest.mark.anyio
async def test_async_client_offloads_a_synchronous_signer() -> None:
    """Keep blocking vault adapters from stalling unrelated coroutines on the async client."""

    class BlockingSigner:
        key_id = SIGNER.key_id

        def sign(self, data: bytes) -> bytes:
            time.sleep(0.03)
            return SIGNER.sign(data)

    wire = SignedMockWire(
        lambda request: WireAnswer(
            body=b'{"partner":{"id":"7c9e6679-7425-40de-944b-e07fc1f90ae7"},"application":{"id":"16fd2706-8baf-433b-82eb-8c7fada847da","scopes":[]}}'
        )
    )
    http = cast(httpx.AsyncClient, wire.client(async_client=True))
    client = AsyncAnisPartnersClient(ClientOptions("https://partners.test"), BlockingSigner(), http_client=http)
    progressed = 0
    finished = asyncio.Event()

    async def heartbeat() -> None:
        nonlocal progressed
        while not finished.is_set():
            progressed += 1
            await asyncio.sleep(0.001)

    pulse = asyncio.create_task(heartbeat())
    try:
        await client.profile.get()
    finally:
        finished.set()
        await pulse
        await client.aclose()
        await http.aclose()
    assert progressed > 1


def test_sync_keyboard_interrupt_records_unknown_with_elapsed_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Count an interrupted synchronous send as unknown before propagating the host interruption."""
    import anis_partners.operations.transport as transport

    class Signal:
        def __init__(self) -> None:
            self.samples: list[tuple[object, object]] = []

        def record(self, value: object, attributes: object = None) -> None:
            self.samples.append((value, attributes))

        def add(self, value: object, attributes: object = None) -> None:
            self.samples.append((value, attributes))

    durations = Signal()
    outcomes = Signal()
    monkeypatch.setattr(transport, "request_duration", durations)
    monkeypatch.setattr(transport, "order_outcomes", outcomes)
    wire = SignedMockWire(lambda request: (_ for _ in ()).throw(KeyboardInterrupt()))
    client, http = _client(wire)
    try:
        with pytest.raises(KeyboardInterrupt):
            client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
    finally:
        client.close()
        http.close()

    assert durations.samples
    assert all(float(cast(float, value)) > 0 for value, _ in durations.samples)
    assert any(
        "anis.order.outcome" in str(attributes) and "unknown" in str(attributes) for _, attributes in outcomes.samples
    )


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
