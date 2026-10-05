"""Capture telemetry in memory so signal shape and secret boundaries are testable without an SDK exporter."""

from __future__ import annotations

import logging
from typing import cast
from uuid import UUID

import httpx
import pytest
from opentelemetry.trace import SpanKind

from anis_partners import AnisPartnersClient, ClientOptions, OrderCompleted, OrderOutcomeUnknown
from anis_partners.signing.errors import RequestSigningError
from tests.operations.test_pipeline import OPERATION, SIGNER, WALLET, _order
from tests.support.sdk_wire import SignedMockWire, WireAnswer


class _Signal:
    """Collect metric samples while preserving their attributes for assertions."""

    def __init__(self) -> None:
        self.samples: list[tuple[object, object]] = []

    def record(self, value: object, attributes: object = None) -> None:
        self.samples.append((value, attributes))

    def add(self, value: object, attributes: object = None) -> None:
        self.samples.append((value, attributes))


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
        )
    )
    http = cast(httpx.Client, wire.client())
    client = AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http)
    try:
        client.orders.create(WALLET, OPERATION, _order())
    finally:
        client.close()
        http.close()

    assert [span.name for span in tracer.spans] == ["anis.partners /v1/wallets/{walletId}/orders"]
    span = tracer.spans[0]
    assert span.attributes["anis.operation_id"] == str(OPERATION)
    assert request_duration.samples
    assert signature_duration.samples
    assert order_outcomes.samples


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

    secrets = ("private-voucher", "private-serial", "enrollment-token", "signature-base", "private-nonce")
    wire = SignedMockWire(
        lambda request: WireAnswer(
            200,
            b'{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"private-voucher","serial":"private-serial"}',
        )
    )
    http = cast(httpx.Client, wire.client())
    client = AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http)
    try:
        client.owned_cards.reveal(WALLET, UUID("4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046"))
    finally:
        client.close()
        http.close()

    captured = repr(
        (
            tracer.spans,
            request_duration.samples,
            signature_duration.samples,
            order_outcomes.samples,
            verification_failures.samples,
            [record.__dict__ for record in caplog.records],
        )
    )
    assert tracer.spans
    assert request_duration.samples
    assert signature_duration.samples
    assert caplog.records
    for secret in secrets:
        assert secret not in captured


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
        result = client.orders.create(WALLET, OPERATION, _order())
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
        result = client.orders.create(WALLET, OPERATION, _order())
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
        result = client.orders.create(WALLET, OPERATION, _order())
    finally:
        client.close()
        http.close()

    assert isinstance(result, OrderCompleted)
    assert result.order.sold_cards is not None
    assert result.order.sold_cards[0].voucher == "delivered-code"


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
