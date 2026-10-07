"""Build frozen requests, verify signed routes' complete answers, and expose one sync/async transport rule set."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, timedelta
from typing import TypeVar
from uuid import UUID

import httpx
from opentelemetry.trace import SpanKind, Status, StatusCode

from anis_partners._internal.clock import Clock, SystemClock
from anis_partners._internal.http_headers import has_true_value
from anis_partners._internal.telemetry import safe_get_logger, safe_log, safe_metric, safe_span
from anis_partners.errors import (
    AnisApiError,
    AnisPartnersError,
    MalformedResponseError,
    create_api_error,
    parse_retry_after,
)
from anis_partners.errors.base import KeyDocumentUnavailableError
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
from anis_partners.signing.content_digest import ContentDigest
from anis_partners.signing.errors import RequestSigningError
from anis_partners.signing.nonce import NonceFactory, RandomNonceFactory
from anis_partners.signing.p256_signer import AsyncRequestSigner, RequestSigner
from anis_partners.signing.partner_request_signer import PartnerRequestSigner
from anis_partners.signing.signature_inputs import SignatureInputs
from anis_partners.signing.signature_profile import SignatureProfile
from anis_partners.signing.signed_request_headers import SignedRequestHeaders
from anis_partners.verification.errors import UnverifiableResponseError
from anis_partners.verification.partner_response_verifier import (
    AsyncPartnerResponseVerifier,
    PartnerResponseVerifier,
)
from anis_partners.verification.verifiable_response import VerifiableResponse

T = TypeVar("T")
DEFAULT_RESUME_DELAY = timedelta(seconds=5)
DOOR_REFUSAL_RESUME_DELAY = timedelta(seconds=60)


@dataclass(frozen=True, slots=True)
class RequestSpec:
    """Keep the concrete URL separate from the route template used in telemetry.

    ``signs_response`` comes from the route table, never from the answer: a signed route's answer must verify,
    and only a route the table marks unsigned is read without verification.
    """

    method: str
    route: str
    path: str
    profile: SignatureProfile | None
    body: bytes | None = None
    operation_id: str | None = None
    authorization: str | None = dataclass_field(default=None, repr=False)
    signs_response: bool = True

    def __repr__(self) -> str:
        """Keep the enrollment authorization token out of native request inspection."""
        authorization = "<redacted>" if self.authorization is not None else None
        return (
            f"RequestSpec(method={self.method!r}, route={self.route!r}, path={self.path!r}, "
            f"profile={self.profile!r}, body={self.body!r}, operation_id={self.operation_id!r}, "
            f"authorization={authorization!r}, signs_response={self.signs_response!r})"
        )


class RequestCore:
    """Apply identical signing, signed-route verification, parsing, and refusal rules to both transports."""

    def __init__(
        self,
        options: ClientOptions,
        signer: RequestSigner | AsyncRequestSigner | None,
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
        self.closed = False
        self.logger = safe_get_logger("anis_partners")

    def body_bytes(self, body: object | None) -> bytes | None:
        """Serialize once before signing so digest and network bytes are the same immutable value."""
        if body is None:
            return None
        to_json = getattr(body, "to_json", None)
        if callable(to_json):
            body = to_json()
        return json.dumps(wire_value(body), ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def _request_facts(
        self, client: httpx.Client | httpx.AsyncClient, spec: RequestSpec
    ) -> tuple[httpx.Request, SignatureInputs | None, int, int, bytes]:
        """Freeze bytes and set each signature header once so retries cannot append stale signatures."""
        url = self.options.authority.rstrip("/") + "/" + spec.path.lstrip("/")
        body = spec.body
        headers: dict[str, str] = {"Accept-Encoding": "identity"}
        if self.options.accept_language is not AcceptLanguage.UNSPECIFIED:
            headers["Accept-Language"] = self.options.accept_language.value
        if spec.authorization is not None:
            headers["Authorization"] = spec.authorization
        if body is not None and body:
            headers["Content-Type"] = "application/json"
        request = client.build_request(
            spec.method,
            url,
            headers=headers,
            content=body,
            extensions={"timeout": httpx.Timeout(self.options.timeout_seconds).as_dict()},
        )
        if spec.profile is None:
            return request, None, 0, 0, body or b""
        if self.request_signer is None or self.signer is None:
            raise ValueError("Signed Partner routes require a request signer.")
        now = self.clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("The request clock must return an aware UTC datetime.")
        now = now.astimezone(UTC)
        created = int(now.timestamp())
        expires = created + self.options.signature_lifetime_seconds
        signed_body = body if body is not None else b""
        raw_path, separator, raw_query = request.url.raw_path.partition(b"?")
        inputs = SignatureInputs(
            method=spec.method,
            authority=request.url.netloc.decode("ascii"),
            path=raw_path.decode("ascii"),
            canonical_query=raw_query.decode("ascii") if separator else "",
            anis_date=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            content_digest=ContentDigest.of(signed_body) if spec.profile is not SignatureProfile.SAFE_READ else None,
            nonce=self.nonces.create() if spec.profile is not SignatureProfile.SAFE_READ else None,
            idempotency_key=spec.operation_id,
            scheme=request.url.scheme,
        )
        return request, inputs, created, expires, signed_body

    @staticmethod
    def _apply_signed_headers(request: httpx.Request, signed: SignedRequestHeaders, body: bytes) -> httpx.Request:
        """Set signature fields on the host-built request so defaults and signed values reach the wire."""
        request.headers["X-Anis-Date"] = signed.anis_date
        if signed.nonce is not None:
            request.headers["Nonce"] = signed.nonce
        if signed.idempotency_key is not None:
            request.headers["Idempotency-Key"] = signed.idempotency_key
        if signed.content_digest is not None:
            request.headers["Content-Digest"] = signed.content_digest
        request.headers["Signature-Input"] = signed.signature_input
        request.headers["Signature"] = signed.signature
        request.stream = httpx.ByteStream(body)
        request.read()
        return request

    def prepare(self, spec: RequestSpec, client: httpx.Client | httpx.AsyncClient) -> httpx.Request:
        """Freeze the exact host-built request before signing so default headers are covered and retained."""
        request, inputs, created, expires, signed_body = self._request_facts(client, spec)
        if spec.profile is None or inputs is None:
            return request
        if self.request_signer is None or self.signer is None:
            raise ValueError("Signed Partner routes require a request signer.")
        signer = self.signer
        started = time.perf_counter()
        signed = self.request_signer.sign(spec.profile, inputs, created, expires)
        safe_metric(
            signature_duration,
            "record",
            (time.perf_counter() - started) * 1000,
            {"anis.signature.profile": spec.profile.value},
        )
        self._apply_signed_headers(request, signed, signed_body)
        self._log(
            1000,
            logging.DEBUG,
            "Signed Anis request %s %s using profile %s with key %s.",
            spec.method,
            spec.route,
            spec.profile.value,
            signer.key_id,
            method=spec.method,
            route=spec.route,
            profile=spec.profile.value,
            key_id=signer.key_id,
        )
        return request

    async def prepare_async(self, spec: RequestSpec, client: httpx.AsyncClient) -> httpx.Request:
        """Await async signers and offload synchronous vault signers without changing request construction."""
        request, inputs, created, expires, signed_body = self._request_facts(client, spec)
        if spec.profile is None or inputs is None:
            return request
        if self.request_signer is None or self.signer is None:
            raise ValueError("Signed Partner routes require a request signer.")
        signer = self.signer
        started = time.perf_counter()
        signed = await self.request_signer.sign_async(spec.profile, inputs, created, expires)
        safe_metric(
            signature_duration,
            "record",
            (time.perf_counter() - started) * 1000,
            {"anis.signature.profile": spec.profile.value},
        )
        self._apply_signed_headers(request, signed, signed_body)
        self._log(
            1000,
            logging.DEBUG,
            "Signed Anis request %s %s using profile %s with key %s.",
            spec.method,
            spec.route,
            spec.profile.value,
            signer.key_id,
            method=spec.method,
            route=spec.route,
            profile=spec.profile.value,
            key_id=signer.key_id,
        )
        return request

    def parse(self, response: httpx.Response, body: bytes, reader: Callable[[object], T]) -> T:
        """Turn answer bytes into a model only after a signed route's verifier has approved the full response."""
        if not response.is_success:
            raise create_api_error(body, response.status_code, joined_headers(response))
        if not body or body.strip() == b"null":
            raise MalformedResponseError(f"The Anis answer for HTTP {response.status_code} had no JSON body.")
        try:
            return reader(body)
        except AnisPartnersError:
            raise
        except Exception:
            model = getattr(reader, "__qualname__", "response model").split(".")[0]
            raise MalformedResponseError(f"The Anis answer could not be read as {model}.") from None

    def verify(
        self,
        request: httpx.Request,
        response: httpx.Response,
        body: bytes,
        verifier: PartnerResponseVerifier | AsyncPartnerResponseVerifier,
    ) -> None:
        """Verify a signed route's buffered response bytes before a status or JSON body reaches operation code."""
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

    def record_response(
        self, spec: RequestSpec, response: httpx.Response, elapsed_ms: float, error_code: str | None = None
    ) -> None:
        """Record bounded route and status fields so concrete identifiers never create telemetry cardinality."""
        attrs: dict[str, str | int] = {
            "anis.client": self.client_name,
            "anis.route": spec.route,
            "http.request.method": spec.method,
            "http.response.status_code": response.status_code,
        }
        if error_code is not None:
            attrs["anis.error.code"] = error_code
        safe_metric(request_duration, "record", elapsed_ms, attrs)
        request_id = joined_headers(response).get("x-request-id")
        self._log(
            1001,
            logging.DEBUG,
            "Anis request completed %s %s with status %s, request %s, in %.1f ms.",
            spec.method,
            spec.route,
            response.status_code,
            request_id or "<none>",
            elapsed_ms,
            method=spec.method,
            route=spec.route,
            status_code=response.status_code,
            request_id=request_id,
            elapsed_ms=elapsed_ms,
        )

    def record_refusal(
        self, spec: RequestSpec, response: httpx.Response, elapsed_ms: float, error: AnisApiError
    ) -> str:
        """Use one refusal mapping for both transports so codes, logs, and metric dimensions cannot drift."""
        code = error.code.value
        self.record_response(spec, response, elapsed_ms, code)
        self._log(
            1002,
            logging.WARNING,
            "Anis refused %s %s: %s (%s), request %s, retryable %s, replayed %s.",
            spec.method,
            spec.route,
            error.raw_code or "unknown",
            error.status,
            error.request_id or "<none>",
            error.is_retryable,
            error.is_replayed,
            method=spec.method,
            route=spec.route,
            code=error.raw_code,
            status_code=error.status,
            request_id=error.request_id,
            retryable=error.is_retryable,
            replayed=error.is_replayed,
        )
        return code

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
            self._log(
                1003,
                logging.ERROR,
                "Anis discarded the unverifiable response (%s). Its content was not used; "
                "this is a channel or clock problem, not a request problem.",
                failure,
                failure=failure,
            )
        else:
            self._log(
                1007,
                logging.WARNING,
                "Anis request %s %s ended without a usable answer (%s) after %.1f ms.",
                spec.method,
                spec.route,
                reason,
                elapsed_ms,
                method=spec.method,
                route=spec.route,
                reason=reason,
                elapsed_ms=elapsed_ms,
            )

    def _log(self, event_id: int, level: int, message: str, *args: object, **fields: object) -> None:
        safe_log(self.logger, level, message, *args, event_id=event_id, **fields)


class SyncTransport:
    """Send synchronously while delegating every signing and response rule to RequestCore."""

    def __init__(self, core: RequestCore, client: httpx.Client, verifier: PartnerResponseVerifier) -> None:
        self.core = core
        self.client = client
        self.verifier = verifier

    def send(self, spec: RequestSpec, reader: Callable[[object], T]) -> tuple[T, httpx.Response, bytes]:
        """Send one prepared exchange; a signed route's answer is refused before parsing unless it fully verifies."""
        if self.core.closed:
            raise RequestSigningError("The client is closed; the request was not sent.")
        span_name = f"anis.partners {spec.route}"
        with safe_span(tracer, span_name, SpanKind.CLIENT) as span:
            span.set_attribute("anis.client", self.core.client_name)
            span.set_attribute("anis.route", spec.route)
            span.set_attribute("http.request.method", spec.method)
            if spec.operation_id:
                span.set_attribute("anis.operation_id", spec.operation_id)
            started = time.perf_counter()
            try:
                request = self.core.prepare(spec, self.client)
            except Exception as exc:
                elapsed = (time.perf_counter() - started) * 1000
                self.core.record_failure(spec, "signing", elapsed_ms=elapsed)
                span.set_attribute("error.type", "signing")
                span.set_status(Status(StatusCode.ERROR, "signing"))
                if isinstance(exc, RequestSigningError):
                    raise
                raise RequestSigningError("The request was not sent because it could not be prepared.") from exc
            try:
                response = self.client.send(request, follow_redirects=False)
                body = response.read()
                if spec.signs_response:
                    self.core.verify(request, response, body, self.verifier)
                elapsed = (time.perf_counter() - started) * 1000
                request_id = joined_headers(response).get("x-request-id")
                if request_id:
                    span.set_attribute("anis.request_id", request_id)
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
            except KeyDocumentUnavailableError as exc:
                elapsed = (time.perf_counter() - started) * 1000
                self.core.record_failure(spec, exc.error_type, elapsed_ms=elapsed)
                span.set_attribute("error.type", exc.error_type)
                span.set_status(Status(StatusCode.ERROR, exc.error_type))
                raise
            except BaseException as exc:
                elapsed = (time.perf_counter() - started) * 1000
                reason = "canceled" if isinstance(exc, KeyboardInterrupt) else "other"
                self.core.record_failure(spec, reason, elapsed_ms=elapsed)
                span.set_attribute("error.type", reason)
                span.set_status(Status(StatusCode.ERROR, reason))
                raise
            try:
                result = self.core.parse(response, body, reader)
            except AnisApiError as exc:
                elapsed = (time.perf_counter() - started) * 1000
                code = self.core.record_refusal(spec, response, elapsed, exc)
                span.set_attribute("anis.error.code", code)
                span.set_status(Status(StatusCode.ERROR, code))
                raise
            except Exception:
                elapsed = (time.perf_counter() - started) * 1000
                self.core.record_failure(spec, "other", elapsed_ms=elapsed)
                span.set_attribute("error.type", "other")
                span.set_status(Status(StatusCode.ERROR, "other"))
                raise
            elapsed = (time.perf_counter() - started) * 1000
            self.core.record_response(spec, response, elapsed)
            span.set_attribute("http.response.status_code", response.status_code)
            return result, response, body


class AsyncTransport:
    """Send asynchronously while delegating every signing and response rule to RequestCore."""

    def __init__(self, core: RequestCore, client: httpx.AsyncClient, verifier: AsyncPartnerResponseVerifier) -> None:
        self.core = core
        self.client = client
        self.verifier = verifier

    async def send(self, spec: RequestSpec, reader: Callable[[object], T]) -> tuple[T, httpx.Response, bytes]:
        """Await sending and, on a signed route, key retrieval, preserving the shared verification and parsing order."""
        if self.core.closed:
            raise RequestSigningError("The client is closed; the request was not sent.")
        span_name = f"anis.partners {spec.route}"
        with safe_span(tracer, span_name, SpanKind.CLIENT) as span:
            span.set_attribute("anis.client", self.core.client_name)
            span.set_attribute("anis.route", spec.route)
            span.set_attribute("http.request.method", spec.method)
            if spec.operation_id:
                span.set_attribute("anis.operation_id", spec.operation_id)
            started = time.perf_counter()
            try:
                request = await self.core.prepare_async(spec, self.client)
            except Exception as exc:
                elapsed = (time.perf_counter() - started) * 1000
                self.core.record_failure(spec, "signing", elapsed_ms=elapsed)
                span.set_attribute("error.type", "signing")
                span.set_status(Status(StatusCode.ERROR, "signing"))
                if isinstance(exc, RequestSigningError):
                    raise
                raise RequestSigningError("The request was not sent because it could not be prepared.") from exc
            try:
                response = await self.client.send(request, follow_redirects=False)
                body = await response.aread()
                if spec.signs_response:
                    await self.core.verify_async(request, response, body, self.verifier)
                elapsed = (time.perf_counter() - started) * 1000
                request_id = joined_headers(response).get("x-request-id")
                if request_id:
                    span.set_attribute("anis.request_id", request_id)
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
            except KeyDocumentUnavailableError as exc:
                elapsed = (time.perf_counter() - started) * 1000
                self.core.record_failure(spec, exc.error_type, elapsed_ms=elapsed)
                span.set_attribute("error.type", exc.error_type)
                span.set_status(Status(StatusCode.ERROR, exc.error_type))
                raise
            except BaseException as exc:
                elapsed = (time.perf_counter() - started) * 1000
                reason = "canceled" if isinstance(exc, asyncio.CancelledError) else "other"
                self.core.record_failure(spec, reason, elapsed_ms=elapsed)
                span.set_attribute("error.type", reason)
                span.set_status(Status(StatusCode.ERROR, reason))
                raise
            try:
                result = self.core.parse(response, body, reader)
            except AnisApiError as exc:
                elapsed = (time.perf_counter() - started) * 1000
                code = self.core.record_refusal(spec, response, elapsed, exc)
                span.set_attribute("anis.error.code", code)
                span.set_status(Status(StatusCode.ERROR, code))
                raise
            except Exception:
                elapsed = (time.perf_counter() - started) * 1000
                self.core.record_failure(spec, "other", elapsed_ms=elapsed)
                span.set_attribute("error.type", "other")
                span.set_status(Status(StatusCode.ERROR, "other"))
                raise
            elapsed = (time.perf_counter() - started) * 1000
            self.core.record_response(spec, response, elapsed)
            span.set_attribute("http.response.status_code", response.status_code)
            return result, response, body


def joined_headers(response: httpx.Response) -> dict[str, str]:
    """Join repeated field values before verification because signatures cover the comma-joined header."""
    values: dict[str, list[str]] = {}
    for name, value in response.headers.multi_items():
        values.setdefault(name.lower(), []).append(value)
    return {name: ", ".join(items) for name, items in values.items()}


def _retry_after(response: httpx.Response) -> timedelta | None:
    """Use only integer seconds, matching the API's bounded Retry-After representation."""
    return parse_retry_after(response.headers.get("Retry-After"))


def validate_order(order: CreateOrderRequest) -> None:
    """Refuse invalid purchase arithmetic locally so a bad total never reaches the gateway."""
    if order.quantity < 1:
        raise ValueError("quantity must be at least 1.")
    if order.expected_unit_price.amount <= 0:
        raise ValueError("expected_unit_price must be greater than zero.")
    expected = order.expected_unit_price.multiply(order.quantity)
    if expected.amount != order.expected_total.amount:
        raise ValueError(
            f"expected_total must equal expected_unit_price multiplied by quantity ({expected.to_wire_amount()})."
        )
    if order.expected_unit_price.currency != order.expected_total.currency:
        raise ValueError("expected_total currency must match expected_unit_price currency.")


def classify_order(order: Order, response: httpx.Response) -> OrderResult:
    """Apply the one order outcome rule set to either transport's verified response."""
    from anis_partners.models.orders import OrderCompleted, OrderProcessing, OrderReplayed

    if response.status_code == 202:
        retry_after = _retry_after(response)
        return OrderProcessing(
            order,
            retry_after if retry_after is not None else DEFAULT_RESUME_DELAY,
            response.headers.get("Location"),
        )
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
    default_delay = DOOR_REFUSAL_RESUME_DELAY if refused_at_the_door(error.code) else DEFAULT_RESUME_DELAY
    delay = error.retry_after if error.retry_after is not None else default_delay
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
    if name == "unknown":
        attrs["error.type"] = reason or "other"
    safe_metric(order_outcomes, "add", 1, attrs)
    core._log(
        1004 if name != "unknown" else 1008,
        logging.INFO if name != "unknown" else logging.WARNING,
        "Anis order %s outcome unknown (%s); resume with the same operation id, never a new one."
        if name == "unknown"
        else "Anis order %s outcome %s.",
        operation_id,
        reason if name == "unknown" else name,
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
        "Anis order %s outcome unknown (%s); resume with the same operation id, never a new one.",
        operation_id,
        reason,
        operation_id=operation_id,
        outcome="unknown",
        reason=reason,
    )
