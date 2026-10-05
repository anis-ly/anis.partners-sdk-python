"""Build frozen requests, verify complete answers, and expose one sync/async transport rule set."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, timedelta
from typing import TypeVar
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from opentelemetry.trace import SpanKind, Status, StatusCode

from anis_partners._internal.clock import Clock, SystemClock
from anis_partners._internal.http_headers import has_true_value
from anis_partners._internal.telemetry import safe_get_logger, safe_log, safe_metric, safe_span
from anis_partners.errors import AnisApiError, create_api_error, empty_body_error
from anis_partners.models._json import wire_value
from anis_partners.models.orders import CreateOrderRequest, Order, OrderResult
from anis_partners.observability.telemetry import (
    order_outcomes,
    request_duration,
    signature_duration,
    tracer,
    verification_failures,
)
from anis_partners.options import AcceptLanguage, ClientOptions
from anis_partners.signing import (
    ContentDigest,
    NonceFactory,
    PartnerRequestSigner,
    RandomNonceFactory,
    SignatureInputs,
    SignatureProfile,
)
from anis_partners.signing.errors import RequestSigningError
from anis_partners.signing.p256_signer import RequestSigner
from anis_partners.verification import (
    AsyncPartnerResponseVerifier,
    PartnerResponseVerifier,
    UnverifiableResponseError,
    VerifiableResponse,
)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RequestSpec:
    """Keep the concrete URL separate from the route template used in telemetry."""

    method: str
    route: str
    path: str
    profile: SignatureProfile | None
    body: bytes | None = None
    operation_id: str | None = None
    authorization: str | None = dataclass_field(default=None, repr=False)

    def __repr__(self) -> str:
        """Keep the enrollment authorization token out of native request inspection."""
        authorization = "<redacted>" if self.authorization is not None else None
        return (
            f"RequestSpec(method={self.method!r}, route={self.route!r}, path={self.path!r}, "
            f"profile={self.profile!r}, body={self.body!r}, operation_id={self.operation_id!r}, "
            f"authorization={authorization!r})"
        )


class RequestCore:
    """Apply identical signing, response verification, parsing, and refusal rules to both transports."""

    def __init__(
        self,
        options: ClientOptions,
        signer: RequestSigner | None,
        clock: Clock | None = None,
        nonces: NonceFactory | None = None,
        client_name: str = "default",
    ) -> None:
        self.options = options
        self.signer = signer
        self.clock = clock or SystemClock()
        self.nonces = nonces or RandomNonceFactory()
        self.client_name = client_name
        self.request_signer = PartnerRequestSigner(signer) if signer is not None else None
        self.logger = safe_get_logger("anis_partners")

    def body_bytes(self, body: object | None) -> bytes | None:
        """Serialize once before signing so digest and network bytes are the same immutable value."""
        if body is None:
            return None
        to_json = getattr(body, "to_json", None)
        if callable(to_json):
            body = to_json()
        return json.dumps(wire_value(body), ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def prepare(self, spec: RequestSpec) -> httpx.Request:
        """Freeze bytes and set each signature header once so retries cannot append stale signatures."""
        url = self.options.authority.rstrip("/") + "/" + spec.path.lstrip("/")
        parsed = urlsplit(url)
        body = spec.body
        headers: dict[str, str] = {"Accept-Encoding": "identity"}
        if self.options.accept_language is not AcceptLanguage.UNSPECIFIED:
            headers["Accept-Language"] = self.options.accept_language.value
        if spec.authorization is not None:
            headers["Authorization"] = spec.authorization
        if body is not None and body:
            headers["Content-Type"] = "application/json"
        content = body
        if spec.profile is not None:
            if self.request_signer is None or self.signer is None:
                raise ValueError("Signed Partner routes require a request signer.")
            now = self.clock.now()
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("The request clock must return an aware UTC datetime.")
            now = now.astimezone(UTC)
            created = int(now.timestamp())
            expires = created + self.options.signature_lifetime_seconds
            signed_body = body if body is not None else b""
            inputs = SignatureInputs(
                method=spec.method,
                authority=parsed.netloc,
                path=parsed.path,
                canonical_query=parsed.query,
                anis_date=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                content_digest=ContentDigest.of(signed_body)
                if spec.profile is not SignatureProfile.SAFE_READ
                else None,
                nonce=self.nonces.create() if spec.profile is not SignatureProfile.SAFE_READ else None,
                idempotency_key=spec.operation_id,
                scheme=parsed.scheme,
            )
            started = time.perf_counter()
            signed = self.request_signer.sign(spec.profile, inputs, created, expires)
            safe_metric(
                signature_duration,
                "record",
                (time.perf_counter() - started) * 1000,
                {"anis.signature.profile": spec.profile.value},
            )
            headers["X-Anis-Date"] = signed.anis_date
            if signed.nonce is not None:
                headers["Nonce"] = signed.nonce
            if signed.idempotency_key is not None:
                headers["Idempotency-Key"] = signed.idempotency_key
            if signed.content_digest is not None:
                headers["Content-Digest"] = signed.content_digest
            headers["Signature-Input"] = signed.signature_input
            headers["Signature"] = signed.signature
            # Every nonce mutation covers a digest and therefore transmits a byte buffer, including b"".
            content = signed_body
            self._log(
                1000,
                logging.DEBUG,
                "Anis request signed",
                method=spec.method,
                path=parsed.path,
                profile=spec.profile.value,
                key_id=str(self.signer.key_id),
            )
        return httpx.Request(spec.method, url, headers=headers, content=content)

    def parse(self, response: httpx.Response, body: bytes, reader: Callable[[object], T]) -> T:
        """Turn verified bytes into a model only after the verifier has approved the full response."""
        if not response.is_success:
            raise create_api_error(body, response.status_code, joined_headers(response))
        if not body or body.strip() == b"null":
            raise empty_body_error(response.status_code)
        return reader(body)

    def verify(
        self,
        request: httpx.Request,
        response: httpx.Response,
        body: bytes,
        verifier: PartnerResponseVerifier | AsyncPartnerResponseVerifier,
    ) -> None:
        """Verify buffered response bytes before a status or JSON body reaches operation code."""
        if isinstance(verifier, AsyncPartnerResponseVerifier):
            raise TypeError("Use verify_async with the asynchronous response verifier.")
        verifier.verify(
            VerifiableResponse(
                response.status_code, joined_headers(response), body, request.headers.get("Signature-Input")
            )
        )

    async def verify_async(
        self, request: httpx.Request, response: httpx.Response, body: bytes, verifier: AsyncPartnerResponseVerifier
    ) -> None:
        """Await only the key source; verification decisions remain the shared verifier's pure rules."""
        await verifier.verify(
            VerifiableResponse(
                response.status_code, joined_headers(response), body, request.headers.get("Signature-Input")
            )
        )

    def record_response(self, spec: RequestSpec, response: httpx.Response, elapsed_ms: float) -> None:
        """Record bounded route and status fields so concrete identifiers never create telemetry cardinality."""
        attrs: dict[str, str | int] = {
            "anis.client": self.client_name,
            "anis.route": spec.route,
            "http.request.method": spec.method,
            "http.response.status_code": response.status_code,
        }
        request_id = joined_headers(response).get("x-request-id")
        if request_id:
            attrs["anis.request_id"] = request_id
        safe_metric(request_duration, "record", elapsed_ms, attrs)
        self._log(
            1001,
            logging.DEBUG,
            "Anis request completed",
            method=spec.method,
            route=spec.route,
            status_code=response.status_code,
            request_id=request_id,
        )

    def record_failure(self, spec: RequestSpec, reason: str, failure: str | None = None, elapsed_ms: float = 0) -> None:
        """Record a refused response or unanswered call without including request or signature bytes."""
        attrs = {
            "anis.client": self.client_name,
            "anis.route": spec.route,
            "http.request.method": spec.method,
            "error.type": reason,
        }
        safe_metric(request_duration, "record", elapsed_ms, attrs)
        if failure is not None:
            safe_metric(verification_failures, "add", 1, {"anis.verification.failure": failure})
            self._log(1003, logging.ERROR, "Anis response discarded, unverifiable", failure=failure)
        else:
            self._log(
                1007,
                logging.WARNING,
                "Anis request ended without a usable answer",
                method=spec.method,
                route=spec.route,
                reason=reason,
            )

    def _log(self, event_id: int, level: int, message: str, **fields: object) -> None:
        safe_log(self.logger, level, message, event_id=event_id, **fields)


class SyncTransport:
    """Send synchronously while delegating every signing and response rule to RequestCore."""

    def __init__(self, core: RequestCore, client: httpx.Client, verifier: PartnerResponseVerifier) -> None:
        self.core = core
        self.client = client
        self.verifier = verifier

    def send(self, spec: RequestSpec, reader: Callable[[object], T]) -> tuple[T, httpx.Response, bytes]:
        """Send one prepared exchange and refuse it before parsing unless its complete answer verifies."""
        span_name = f"anis.partners {spec.route}"
        with safe_span(tracer, span_name, SpanKind.CLIENT) as span:
            span.set_attribute("anis.client", self.core.client_name)
            span.set_attribute("anis.route", spec.route)
            span.set_attribute("http.request.method", spec.method)
            if spec.operation_id:
                span.set_attribute("anis.operation_id", spec.operation_id)
            started = time.perf_counter()
            try:
                request = self.core.prepare(spec)
            except RequestSigningError:
                elapsed = (time.perf_counter() - started) * 1000
                self.core.record_failure(spec, "signing", elapsed_ms=elapsed)
                span.set_attribute("error.type", "signing")
                span.set_status(Status(StatusCode.ERROR, "signing"))
                raise
            try:
                response = self.client.send(request, follow_redirects=False)
                body = response.read()
                self.core.verify(request, response, body, self.verifier)
                span.set_attribute("http.response.status_code", response.status_code)
                elapsed = (time.perf_counter() - started) * 1000
                self.core.record_response(spec, response, elapsed)
            except UnverifiableResponseError as exc:
                elapsed = (time.perf_counter() - started) * 1000
                self.core.record_failure(spec, "unverifiable", exc.failure.value, elapsed)
                span.set_attribute("error.type", "unverifiable")
                span.set_status(Status(StatusCode.ERROR, "unverifiable"))
                raise
            except httpx.TransportError as exc:
                reason = "timeout" if isinstance(exc, httpx.TimeoutException) else "connection"
                elapsed = (time.perf_counter() - started) * 1000
                self.core.record_failure(spec, reason, elapsed_ms=elapsed)
                span.set_attribute("error.type", reason)
                span.set_status(Status(StatusCode.ERROR, reason))
                raise
            except Exception:
                elapsed = (time.perf_counter() - started) * 1000
                self.core.record_failure(spec, "other", elapsed_ms=elapsed)
                span.set_attribute("error.type", "other")
                span.set_status(Status(StatusCode.ERROR, "other"))
                raise
            try:
                result = self.core.parse(response, body, reader)
            except AnisApiError as exc:
                span.set_attribute("anis.error.code", exc.raw_code or "unknown")
                span.set_status(Status(StatusCode.ERROR, "refused"))
                self.core._log(
                    1002,
                    logging.WARNING,
                    "Anis refused request",
                    method=spec.method,
                    route=spec.route,
                    code=exc.raw_code,
                    status_code=exc.status,
                    request_id=exc.request_id,
                    retryable=exc.is_retryable,
                    replayed=exc.is_replayed,
                )
                raise
            return result, response, body


class AsyncTransport:
    """Send asynchronously while delegating every signing and response rule to RequestCore."""

    def __init__(self, core: RequestCore, client: httpx.AsyncClient, verifier: AsyncPartnerResponseVerifier) -> None:
        self.core = core
        self.client = client
        self.verifier = verifier

    async def send(self, spec: RequestSpec, reader: Callable[[object], T]) -> tuple[T, httpx.Response, bytes]:
        """Await sending and key retrieval, preserving the shared verification and parsing order."""
        span_name = f"anis.partners {spec.route}"
        with safe_span(tracer, span_name, SpanKind.CLIENT) as span:
            span.set_attribute("anis.client", self.core.client_name)
            span.set_attribute("anis.route", spec.route)
            span.set_attribute("http.request.method", spec.method)
            if spec.operation_id:
                span.set_attribute("anis.operation_id", spec.operation_id)
            started = time.perf_counter()
            try:
                request = self.core.prepare(spec)
            except RequestSigningError:
                elapsed = (time.perf_counter() - started) * 1000
                self.core.record_failure(spec, "signing", elapsed_ms=elapsed)
                span.set_attribute("error.type", "signing")
                span.set_status(Status(StatusCode.ERROR, "signing"))
                raise
            try:
                response = await self.client.send(request, follow_redirects=False)
                body = await response.aread()
                await self.core.verify_async(request, response, body, self.verifier)
                span.set_attribute("http.response.status_code", response.status_code)
                elapsed = (time.perf_counter() - started) * 1000
                self.core.record_response(spec, response, elapsed)
            except UnverifiableResponseError as exc:
                elapsed = (time.perf_counter() - started) * 1000
                self.core.record_failure(spec, "unverifiable", exc.failure.value, elapsed)
                span.set_attribute("error.type", "unverifiable")
                span.set_status(Status(StatusCode.ERROR, "unverifiable"))
                raise
            except httpx.TransportError as exc:
                reason = "timeout" if isinstance(exc, httpx.TimeoutException) else "connection"
                elapsed = (time.perf_counter() - started) * 1000
                self.core.record_failure(spec, reason, elapsed_ms=elapsed)
                span.set_attribute("error.type", reason)
                span.set_status(Status(StatusCode.ERROR, reason))
                raise
            except Exception:
                elapsed = (time.perf_counter() - started) * 1000
                self.core.record_failure(spec, "other", elapsed_ms=elapsed)
                span.set_attribute("error.type", "other")
                span.set_status(Status(StatusCode.ERROR, "other"))
                raise
            try:
                result = self.core.parse(response, body, reader)
            except AnisApiError as exc:
                span.set_attribute("anis.error.code", exc.raw_code or "unknown")
                span.set_status(Status(StatusCode.ERROR, "refused"))
                self.core._log(
                    1002,
                    logging.WARNING,
                    "Anis refused request",
                    method=spec.method,
                    route=spec.route,
                    code=exc.raw_code,
                    status_code=exc.status,
                    request_id=exc.request_id,
                    retryable=exc.is_retryable,
                    replayed=exc.is_replayed,
                )
                raise
            return result, response, body


def joined_headers(response: httpx.Response) -> dict[str, str]:
    """Join repeated field values before verification because signatures cover the comma-joined header."""
    values: dict[str, list[str]] = {}
    for name, value in response.headers.multi_items():
        values.setdefault(name.lower(), []).append(value)
    return {name: ", ".join(items) for name, items in values.items()}


def _retry_after(response: httpx.Response) -> timedelta | None:
    """Use only integer seconds, matching the API's bounded Retry-After representation."""
    value = response.headers.get("Retry-After")
    return timedelta(seconds=int(value)) if value and value.isascii() and value.isdigit() else None


def validate_order(order: CreateOrderRequest) -> None:
    """Refuse invalid purchase arithmetic locally so a bad total never reaches the gateway."""
    if order.quantity < 1:
        raise ValueError("An order must be for at least one card.")
    if order.expected_unit_price.amount <= 0:
        raise ValueError("ExpectedUnitPrice must be greater than zero.")
    expected = order.expected_unit_price.multiply(order.quantity)
    if expected.amount != order.expected_total.amount:
        raise ValueError(
            f"ExpectedTotal is {order.expected_total.to_wire_amount()} but unit times quantity is "
            f"{expected.to_wire_amount()}. The gateway computes this without floating point and refuses a mismatch; "
            "use Money.multiply rather than a float."
        )
    if order.expected_unit_price.currency != order.expected_total.currency:
        raise ValueError("ExpectedUnitPrice and ExpectedTotal must carry the same currency.")


def classify_order(order: Order, response: httpx.Response, operation_id: UUID, resuming: bool) -> OrderResult:
    """Apply the one order outcome rule set to either transport's verified response."""
    from anis_partners.models.orders import OrderCompleted, OrderProcessing, OrderReplayed

    if response.status_code == 202:
        return OrderProcessing(order, _retry_after(response) or timedelta(seconds=5), response.headers.get("Location"))
    credentials = getattr(order, "sold_cards", None)
    if credentials:
        return OrderCompleted(order)
    if has_true_value(response.headers.get("Idempotency-Replayed")):
        return OrderReplayed(order)
    return OrderCompleted(order)


def classify_refusal(error: AnisApiError, operation_id: UUID, resuming: bool) -> OrderResult:
    """Keep uncertain or resumed refusals open and only close outcomes Anis decided not to place."""
    from anis_partners.errors import OrderRefusalOutcome, refused_at_the_door
    from anis_partners.models.orders import OrderNotPlaced, OrderOutcomeUnknown

    if error.order_outcome is OrderRefusalOutcome.NOT_PLACED and (error.is_replayed or not resuming):
        return OrderNotPlaced(operation_id, error)
    delay = error.retry_after or (timedelta(seconds=60) if refused_at_the_door(error.code) else timedelta(seconds=5))
    return OrderOutcomeUnknown(operation_id, delay, error)


def record_order_outcome(core: RequestCore, outcome: OrderResult, operation_id: str, reason: str | None = None) -> None:
    """Count only actionable outcomes and attach the caller-owned id to safe structured events."""
    from anis_partners.models.orders import (
        OrderCompleted,
        OrderNotPlaced,
        OrderOutcomeUnknown,
        OrderProcessing,
        OrderReplayed,
    )

    if isinstance(outcome, OrderNotPlaced):
        return
    if isinstance(outcome, OrderOutcomeUnknown):
        name = "unknown"
        if isinstance(outcome.cause, AnisApiError) and outcome.cause.problem.title == "Empty body":
            reason = reason or "empty_body"
        reason = reason or getattr(outcome.cause, "raw_code", None) or type(outcome.cause).__name__
    elif isinstance(outcome, OrderCompleted):
        name = "completed"
    elif isinstance(outcome, OrderProcessing):
        name = "processing"
    elif isinstance(outcome, OrderReplayed):
        name = "replayed"
    else:
        return
    attrs = {"anis.client": core.client_name, "anis.order.outcome": name}
    if name == "unknown" and reason:
        attrs["error.type"] = reason
    safe_metric(order_outcomes, "add", 1, attrs)
    core._log(
        1004 if name != "unknown" else 1008,
        logging.INFO if name != "unknown" else logging.WARNING,
        f"Anis order {operation_id} outcome UNKNOWN ({reason}): resume it with the same operation id, never a new one."
        if name == "unknown"
        else "Anis order outcome",
        operation_id=operation_id,
        outcome=name,
        reason=reason,
    )


def record_unknown_order(core: RequestCore, operation_id: str, reason: str) -> None:
    """Count caller cancellation before rethrowing it because the purchase may still have reached Anis."""
    safe_metric(
        order_outcomes,
        "add",
        1,
        {"anis.client": core.client_name, "anis.order.outcome": "unknown", "error.type": reason},
    )
    core._log(
        1008,
        logging.WARNING,
        f"Anis order {operation_id} outcome UNKNOWN ({reason}): resume it with the same operation id, never a new one.",
        operation_id=operation_id,
        outcome="unknown",
        reason=reason,
    )
