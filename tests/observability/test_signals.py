"""Capture telemetry in memory so signal shape and secret boundaries are testable without an SDK exporter."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import cast
from uuid import UUID

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from opentelemetry.trace import SpanKind

from anis_partners import (
    AnisApiError,
    AnisPartnersClient,
    AsyncAnisPartnersClient,
    ClientOptions,
    MalformedResponseError,
    OrderCompleted,
    OrderNotPlaced,
    OrderOutcomeUnknown,
    PemP256Signer,
)
from anis_partners.signing.errors import RequestSigningError
from tests.support.partner import OPERATION, SIGNER, WALLET
from tests.support.partner import order as _order
from tests.support.sdk_wire import SignedMockWire, WireAnswer


class _Signal:
    """Collect metric samples while preserving their attributes for assertions."""

    def __init__(self) -> None:
        self.samples: list[tuple[object, Mapping[str, object]]] = []

    def record(self, value: object, attributes: Mapping[str, object] | None = None) -> None:
        self.samples.append((value, attributes or {}))

    def add(self, value: object, attributes: Mapping[str, object] | None = None) -> None:
        self.samples.append((value, attributes or {}))


class _Span:
    """Capture span names, attributes, and failure status without requiring an OTel SDK package."""

    def __init__(self, name: str, record_exception: bool, set_status_on_exception: bool) -> None:
        self.name = name
        self.attributes: dict[str, object] = {}
        self.status: object | None = None
        self.events: list[object] = []
        self.record_exception = record_exception
        self.set_status_on_exception = set_status_on_exception

    def __enter__(self) -> _Span:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc is not None and self.record_exception:
            self.events.append(exc)
        if exc is not None and self.set_status_on_exception:
            self.status = exc
        return None

    def set_attribute(self, name: str, value: object) -> None:
        self.attributes[name] = value

    def set_status(self, status: object) -> None:
        self.status = status


class _Tracer:
    """Store spans created by the transport for an in-memory observability assertion."""

    def __init__(self) -> None:
        self.spans: list[_Span] = []
        self.options: list[dict[str, object]] = []

    def start_as_current_span(self, name: str, **kwargs: object) -> _Span:
        self.options.append(kwargs)
        span = _Span(name, bool(kwargs.get("record_exception")), bool(kwargs.get("set_status_on_exception")))
        self.spans.append(span)
        return span


def _break_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every host signal fail so no operation can accidentally depend on telemetry success."""
    import anis_partners.operations.transport as transport
    import anis_partners.verification.async_http_signing_key_source as async_key_source
    import anis_partners.verification.http_signing_key_source as key_source

    class ThrowingSignal:
        def record(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("meter unavailable")

        def add(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("meter unavailable")

    class ThrowingTracer:
        def start_as_current_span(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("tracer unavailable")

    class ThrowingLogger:
        def log(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("logger unavailable")

    original_get_logger = logging.getLogger
    monkeypatch.setattr(
        logging,
        "getLogger",
        lambda name=None: ThrowingLogger() if name == "anis_partners" else original_get_logger(name),
    )
    monkeypatch.setattr(transport, "tracer", ThrowingTracer())
    for name in ("request_duration", "signature_duration", "verification_failures", "order_outcomes"):
        monkeypatch.setattr(transport, name, ThrowingSignal())
    monkeypatch.setattr(key_source, "signing_key_fetches", ThrowingSignal())
    monkeypatch.setattr(async_key_source, "signing_key_fetches", ThrowingSignal())


def test_calls_emit_route_template_spans_duration_and_order_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep spans and measures useful for operations while avoiding concrete resource paths."""
    import anis_partners.operations.transport as transport

    tracer = _Tracer()
    request_duration = _Signal()
    signature_duration = _Signal()
    order_outcomes = _Signal()
    monkeypatch.setattr(transport, "tracer", tracer)
    monkeypatch.setattr(transport, "request_duration", request_duration)
    monkeypatch.setattr(transport, "signature_duration", signature_duration)
    monkeypatch.setattr(transport, "order_outcomes", order_outcomes)

    wire = SignedMockWire(
        lambda request: WireAnswer(
            201,
            b'{"status":"completed","soldCards":[{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"private-voucher"}]}',
            {"X-Request-Id": "request-telemetry-check"},
        )
    )
    http = cast(httpx.Client, wire.client())
    client = AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http)
    try:
        client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
    finally:
        client.close()
        http.close()

    assert [span.name for span in tracer.spans] == ["anis.partners /v1/wallets/{walletId}/orders"]
    span = tracer.spans[0]
    assert span.attributes["anis.operation_id"] == str(OPERATION)
    assert span.attributes["anis.request_id"] == "request-telemetry-check"
    assert all("request_id" not in repr(attributes) for _, attributes in request_duration.samples)
    assert request_duration.samples
    assert signature_duration.samples
    assert order_outcomes.samples


def test_signing_event_includes_the_selected_key_id(caplog: pytest.LogCaptureFixture) -> None:
    """Include the enrolled key id in the signing event so operators can diagnose key selection."""
    caplog.set_level(logging.DEBUG, logger="anis_partners")
    wire = SignedMockWire()
    http = cast(httpx.Client, wire.client())
    client = AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http)
    try:
        client.profile.get()
    finally:
        client.close()
        http.close()
    signed = next(record for record in caplog.records if getattr(record, "event_id", None) == 1000)
    assert SIGNER.key_id in signed.getMessage()


def test_key_document_http_failure_is_a_connection_type_unknown_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    """Classify failed key-document status as a connection failure in both request and order metrics."""
    import anis_partners.operations.transport as transport

    request_duration = _Signal()
    order_outcomes = _Signal()
    monkeypatch.setattr(transport, "request_duration", request_duration)
    monkeypatch.setattr(transport, "order_outcomes", order_outcomes)
    wire = SignedMockWire(lambda request: WireAnswer(201, b'{"status":"completed"}'))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("partner-signing-keys.json"):
            return httpx.Response(503, request=request)
        return wire.handle(request)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http)
    try:
        outcome = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
    finally:
        client.close()
        http.close()
    assert isinstance(outcome, OrderOutcomeUnknown)
    assert any(attributes.get("error.type") == "connection" for _, attributes in request_duration.samples)
    assert any(attributes.get("error.type") == "connection" for _, attributes in order_outcomes.samples)


@pytest.mark.anyio
async def test_key_document_timeout_is_a_timeout_type_unknown_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    """Classify an async key-document timeout as timeout rather than an unhandled internal failure."""
    import anis_partners.operations.transport as transport

    request_duration = _Signal()
    order_outcomes = _Signal()
    monkeypatch.setattr(transport, "request_duration", request_duration)
    monkeypatch.setattr(transport, "order_outcomes", order_outcomes)
    wire = SignedMockWire(lambda request: WireAnswer(201, b'{"status":"completed"}'))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("partner-signing-keys.json"):
            raise httpx.ReadTimeout("slow", request=request)
        return wire.handle(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncAnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http)
    try:
        outcome = await client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
    finally:
        await client.aclose()
        await http.aclose()
    assert isinstance(outcome, OrderOutcomeUnknown)
    assert any(attributes.get("error.type") == "timeout" for _, attributes in request_duration.samples)
    assert any(attributes.get("error.type") == "timeout" for _, attributes in order_outcomes.samples)


def test_no_secret_reaches_any_captured_telemetry_signal(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Keep credential material out of spans, measures, and logs because telemetry leaves the partner host."""
    import anis_partners.operations.transport as transport

    tracer = _Tracer()
    request_duration = _Signal()
    signature_duration = _Signal()
    order_outcomes = _Signal()
    verification_failures = _Signal()
    monkeypatch.setattr(transport, "tracer", tracer)
    monkeypatch.setattr(transport, "request_duration", request_duration)
    monkeypatch.setattr(transport, "signature_duration", signature_duration)
    monkeypatch.setattr(transport, "order_outcomes", order_outcomes)
    monkeypatch.setattr(transport, "verification_failures", verification_failures)
    caplog.set_level(logging.DEBUG, logger="anis_partners")

    known_nonce = "known-private-nonce"
    known_token = "-".join(("known", "enrollment", "token"))
    private_key = ec.generate_private_key(ec.SECP256R1())
    known_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pem_signer = PemP256Signer.from_pem(known_pem).for_key(SIGNER.key_id)
    signature_bases: list[bytes] = []

    class RecordingPemSigner:
        key_id = pem_signer.key_id

        def sign(self, data: bytes) -> bytes:
            signature_bases.append(data)
            return pem_signer.sign(data)

    response_count = 0

    class FixedNonce:
        def create(self) -> str:
            return known_nonce

    def answer(request: httpx.Request) -> WireAnswer:
        nonlocal response_count
        if "/v1/enrollments/" in request.url.path:
            return WireAnswer(
                body=b'{"invitationId":"3f2a9c14-8d6e-4b21-9f07-5c8ab2d61e43","state":"pendingPublicKey"}'
            )
        response_count += 1
        if response_count == 1:
            return WireAnswer(
                200,
                b'{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"private-voucher","serialNumber":"private-serial"}',
            )
        return WireAnswer(
            200,
            b'{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"private-voucher","serialNumber":"private-serial","revealedAt":"not-a-date"}',
        )

    wire = SignedMockWire(answer)
    http = cast(httpx.Client, wire.client())
    client = AnisPartnersClient(
        ClientOptions("https://partners.test"), RecordingPemSigner(), http_client=http, nonce_factory=FixedNonce()
    )
    try:
        credential = client.owned_cards.reveal(WALLET, UUID("4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046"))
        assert credential.serial_number == "private-serial"
        assert credential.voucher == "private-voucher"
        with pytest.raises(MalformedResponseError) as malformed:
            client.owned_cards.reveal(WALLET, UUID("4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046"))
        assert malformed.value.__cause__ is None
        assert "private-voucher" not in str(malformed.value)
        from anis_partners.enrollment.client import AnisEnrollmentClient

        with AnisEnrollmentClient(
            "https://partners.test", UUID("3f2a9c14-8d6e-4b21-9f07-5c8ab2d61e43"), known_token, http_client=http
        ) as enrollment:
            assert enrollment.get().state == "pendingPublicKey"
    finally:
        client.close()
        http.close()

    cause_chain: list[tuple[str, str]] = []
    cause: BaseException | None = malformed.value
    while cause is not None:
        cause_chain.append((str(cause), repr(cause.__cause__)))
        cause = cause.__cause__
    captured = repr(
        (
            tracer.spans,
            request_duration.samples,
            signature_duration.samples,
            order_outcomes.samples,
            verification_failures.samples,
            [record.__dict__ for record in caplog.records],
            cause_chain,
        )
    )
    secrets = (
        "private-voucher",
        "private-serial",
        known_token,
        known_nonce,
        known_pem.decode("ascii"),
        signature_bases[0].decode("ascii"),
    )
    assert tracer.spans
    assert request_duration.samples
    assert signature_duration.samples
    assert caplog.records
    for secret in secrets:
        assert secret not in captured


def test_signer_secret_in_exception_never_reaches_span_event_or_status(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Keep vault exception text out of recorded span events and status descriptions."""
    import anis_partners.operations.transport as transport

    known_pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pem_signer = PemP256Signer.from_pem(known_pem).for_key(SIGNER.key_id)
    sentinel = known_pem.decode("ascii")
    tracer = _Tracer()
    monkeypatch.setattr(transport, "tracer", tracer)

    class FailingSigner:
        key_id = SIGNER.key_id

        def sign(self, data: bytes) -> bytes:
            pem_signer.sign(data)
            raise RuntimeError(sentinel)

    wire = SignedMockWire()
    http = cast(httpx.Client, wire.client())
    client = AnisPartnersClient(ClientOptions("https://partners.test"), FailingSigner(), http_client=http)
    caplog.set_level(logging.DEBUG, logger="anis_partners")
    try:
        with pytest.raises(RequestSigningError) as caught:
            client.profile.get()
    finally:
        client.close()
        http.close()

    span = tracer.spans[0]
    captured = repr((span.attributes, span.events, span.status, [record.__dict__ for record in caplog.records]))
    assert tracer.options[0]["record_exception"] is False
    assert tracer.options[0]["set_status_on_exception"] is False
    assert span.events == []
    assert sentinel not in str(caught.value)
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert str(caught.value.__cause__) == sentinel
    assert "signing" in captured
    assert sentinel not in captured


def test_timeout_marks_span_and_order_metric_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expose an unanswered purchase as a failed measured call and an unknown outcome for safe recovery."""
    import anis_partners.operations.transport as transport

    tracer = _Tracer()
    request_duration = _Signal()
    signature_duration = _Signal()
    order_outcomes = _Signal()
    monkeypatch.setattr(transport, "tracer", tracer)
    monkeypatch.setattr(transport, "request_duration", request_duration)
    monkeypatch.setattr(transport, "signature_duration", signature_duration)
    monkeypatch.setattr(transport, "order_outcomes", order_outcomes)

    def timeout(request: httpx.Request) -> WireAnswer:
        raise httpx.ReadTimeout("response timed out", request=request)

    wire = SignedMockWire(timeout)
    http = cast(httpx.Client, wire.client())
    client = AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http)
    try:
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
    finally:
        client.close()
        http.close()

    assert isinstance(result, OrderOutcomeUnknown)
    assert tracer.spans[0].status is not None
    assert request_duration.samples
    assert signature_duration.samples
    assert any(
        "anis.order.outcome" in repr(attributes) and "unknown" in repr(attributes)
        for _, attributes in order_outcomes.samples
    )


def test_discarded_answer_records_the_verification_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Record the bounded refusal reason so operators can distinguish tampering from a network outage."""
    import anis_partners.operations.transport as transport

    verification_failures = _Signal()
    order_outcomes = _Signal()
    monkeypatch.setattr(transport, "verification_failures", verification_failures)
    monkeypatch.setattr(transport, "order_outcomes", order_outcomes)
    wire = SignedMockWire(
        lambda request: WireAnswer(
            status=201,
            body=b'{"status":"completed","soldCards":[{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"V"}]}',
        )
    )

    def alter(request: httpx.Request) -> httpx.Response:
        response = wire.handle(request)
        if request.url.path == "/.well-known/partner-signing-keys.json":
            return response
        return httpx.Response(
            response.status_code, headers=response.headers, content=b'{"voucher":"changed"}', request=request
        )

    http = httpx.Client(transport=httpx.MockTransport(alter))
    client = AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http)
    try:
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
    finally:
        client.close()
        http.close()

    assert isinstance(result, OrderOutcomeUnknown)
    assert verification_failures.samples
    assert "content_digest_mismatch" in repr(verification_failures.samples)
    assert "unknown" in repr(order_outcomes.samples)


def test_throwing_logger_does_not_lose_completed_order_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """A broken host logger cannot replace a verified purchase result containing delivered card codes."""

    class ThrowingLogger:
        def log(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("logger is unavailable")

    original_get_logger = logging.getLogger

    def get_logger(name: str | None = None) -> logging.Logger | ThrowingLogger:
        return ThrowingLogger() if name == "anis_partners" else original_get_logger(name)

    monkeypatch.setattr(logging, "getLogger", get_logger)
    wire = SignedMockWire(
        lambda request: WireAnswer(
            201,
            b'{"status":"completed","soldCards":[{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"delivered-code"}]}',
        )
    )
    http = cast(httpx.Client, wire.client())
    client = AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http)
    try:
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
    finally:
        client.close()
        http.close()

    assert isinstance(result, OrderCompleted)
    assert result.order.sold_cards is not None
    assert result.order.sold_cards[0].voucher == "delivered-code"


def test_throwing_meter_and_tracer_do_not_lose_completed_order_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a verified completion usable when host tracing and metric providers throw during recording."""
    import anis_partners.operations.transport as transport
    import anis_partners.verification.http_signing_key_source as key_source

    class ThrowingSignal:
        def record(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("meter unavailable")

        def add(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("meter unavailable")

    class ThrowingTracer:
        def start_as_current_span(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("tracer unavailable")

    class ThrowingLogger:
        def log(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("logger unavailable")

    original_get_logger = logging.getLogger
    monkeypatch.setattr(
        logging,
        "getLogger",
        lambda name=None: ThrowingLogger() if name == "anis_partners" else original_get_logger(name),
    )
    monkeypatch.setattr(transport, "tracer", ThrowingTracer())
    for name in ("request_duration", "signature_duration", "verification_failures", "order_outcomes"):
        monkeypatch.setattr(transport, name, ThrowingSignal())
    monkeypatch.setattr(key_source, "signing_key_fetches", ThrowingSignal())

    wire = SignedMockWire(
        lambda request: WireAnswer(
            201,
            b'{"status":"completed","soldCards":[{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"delivered-code"}]}',
        )
    )
    http = cast(httpx.Client, wire.client())
    client = AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http)
    try:
        result = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
    finally:
        client.close()
        http.close()

    assert isinstance(result, OrderCompleted)
    assert result.order.sold_cards is not None
    assert result.order.sold_cards[0].voucher == "delivered-code"


def _all_path_wire() -> SignedMockWire:
    """Serve one result per operation path so the telemetry fault fixture exercises distinct SDK outcomes."""
    order_number = 0

    def answer(request: httpx.Request) -> WireAnswer:
        nonlocal order_number
        path = request.url.path
        if path == "/v1/profile":
            return WireAnswer(
                body=b'{"partner":{"id":"7c9e6679-7425-40de-944b-e07fc1f90ae7"},"application":{"id":"16fd2706-8baf-433b-82eb-8c7fada847da","scopes":[]}}'
            )
        if path.endswith("/reveal"):
            return WireAnswer(body=b'{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"delivered-code"}')
        if path.endswith("/orders"):
            order_number += 1
            if order_number == 1:
                return WireAnswer(
                    201,
                    b'{"status":"completed","soldCards":[{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"delivered-code"}]}',
                )
            if order_number == 2:
                return WireAnswer(409, b'{"status":409,"code":"price_changed"}')
            raise httpx.ReadTimeout("answer timed out", request=request)
        return WireAnswer(body=b'{"invitationId":"3f2a9c14-8d6e-4b21-9f07-5c8ab2d61e43","state":"pendingPublicKey"}')

    return SignedMockWire(answer)


def test_throwing_telemetry_does_not_change_sync_read_reveal_order_or_enrollment_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep all sync operation paths usable when logging, metrics, tracing, and key-fetch signals throw."""
    from anis_partners.enrollment.client import AnisEnrollmentClient

    _break_telemetry(monkeypatch)
    wire = _all_path_wire()
    http = cast(httpx.Client, wire.client())
    with AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http) as client:
        assert client.profile.get().application is not None
        assert (
            client.owned_cards.reveal(WALLET, UUID("4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046")).voucher == "delivered-code"
        )
        completed = client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
        refused = client.orders.create(
            wallet_id=WALLET,
            operation_id=UUID("16fd2706-8baf-433b-82eb-8c7fada847db"),
            order=_order(),
        )
        unknown = client.orders.create(
            wallet_id=WALLET,
            operation_id=UUID("16fd2706-8baf-433b-82eb-8c7fada847dc"),
            order=_order(),
        )
    with AnisEnrollmentClient(
        "https://partners.test", UUID("3f2a9c14-8d6e-4b21-9f07-5c8ab2d61e43"), "enrollment-token", http_client=http
    ) as enrollment:
        assert enrollment.get().state == "pendingPublicKey"
    http.close()
    assert isinstance(completed, OrderCompleted)
    assert isinstance(refused, OrderNotPlaced)
    assert isinstance(refused.refusal, AnisApiError)
    assert isinstance(unknown, OrderOutcomeUnknown)


@pytest.mark.anyio
async def test_throwing_telemetry_does_not_change_async_read_reveal_order_or_enrollment_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep every async operation path usable when awaited sends encounter broken host observability."""
    from anis_partners.enrollment.client import AsyncAnisEnrollmentClient

    _break_telemetry(monkeypatch)
    wire = _all_path_wire()
    http = cast(httpx.AsyncClient, wire.client(async_client=True))
    async with AsyncAnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http) as client:
        assert (await client.profile.get()).application is not None
        revealed = await client.owned_cards.reveal(WALLET, UUID("4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046"))
        assert revealed.voucher == "delivered-code"
        completed = await client.orders.create(wallet_id=WALLET, operation_id=OPERATION, order=_order())
        refused = await client.orders.create(
            wallet_id=WALLET,
            operation_id=UUID("16fd2706-8baf-433b-82eb-8c7fada847db"),
            order=_order(),
        )
        unknown = await client.orders.create(
            wallet_id=WALLET,
            operation_id=UUID("16fd2706-8baf-433b-82eb-8c7fada847dc"),
            order=_order(),
        )
    async with AsyncAnisEnrollmentClient(
        "https://partners.test", UUID("3f2a9c14-8d6e-4b21-9f07-5c8ab2d61e43"), "enrollment-token", http_client=http
    ) as enrollment:
        assert (await enrollment.get()).state == "pendingPublicKey"
    await http.aclose()
    assert isinstance(completed, OrderCompleted)
    assert isinstance(refused, OrderNotPlaced)
    assert isinstance(refused.refusal, AnisApiError)
    assert isinstance(unknown, OrderOutcomeUnknown)


def test_signer_secret_is_not_recorded_on_the_span(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable automatic span exception capture so a vault error's secret message stays caller-only."""
    import anis_partners.operations.transport as transport

    class FailingSigner:
        key_id = "9e96dc41-c715-4cc4-b1aa-836fe42ad0bb"

        def sign(self, data: bytes) -> bytes:
            raise OSError("vault-secret-material")

    tracer = _Tracer()
    monkeypatch.setattr(transport, "tracer", tracer)
    wire = SignedMockWire()
    http = cast(httpx.Client, wire.client())
    client = AnisPartnersClient(ClientOptions("https://partners.test"), FailingSigner(), http_client=http)
    try:
        with pytest.raises(RequestSigningError) as caught:
            client.profile.get()
    finally:
        client.close()
        http.close()

    assert isinstance(caught.value.__cause__, OSError)
    assert tracer.options == [{"kind": SpanKind.CLIENT, "record_exception": False, "set_status_on_exception": False}]
    assert len(tracer.spans) == 1
    span = tracer.spans[0]
    assert span.events == []
    assert "vault-secret-material" not in repr((span.attributes, span.status, span.events))
    assert getattr(span.status, "description", None) == "signing"
