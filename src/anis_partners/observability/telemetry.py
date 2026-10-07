"""Stable SDK instrumentation names without requiring an OpenTelemetry SDK in the host."""

from collections.abc import Callable
from typing import TypeVar

from opentelemetry.metrics import Counter, Histogram, Meter, get_meter
from opentelemetry.trace import Tracer, get_tracer

INSTRUMENTATION_SCOPE = "anis_partners"
INSTRUMENTATION_VERSION = "1.1.0"
T = TypeVar("T")


class Tags:
    """Name bounded telemetry dimensions so hosts can filter SDK signals consistently."""

    CLIENT = "anis.client"
    ROUTE = "anis.route"
    REQUEST_ID = "anis.request_id"
    OPERATION_ID = "anis.operation_id"
    ERROR_CODE = "anis.error.code"
    ERROR_TYPE = "error.type"
    VERIFICATION_FAILURE = "anis.verification.failure"
    ORDER_OUTCOME = "anis.order.outcome"
    FETCH_REASON = "anis.fetch.reason"
    SIGNATURE_PROFILE = "anis.signature.profile"


class _NoOpInstrument:
    """Keep request handling available when host meter setup raises during SDK import."""

    def record(self, value: object, attributes: object = None) -> None:
        """Ignore a recording when no host instrument is available."""

    def add(self, value: object, attributes: object = None) -> None:
        """Ignore a count when no host instrument is available."""


def _provider(factory: Callable[[str, str], T]) -> T | None:
    try:
        return factory(INSTRUMENTATION_SCOPE, INSTRUMENTATION_VERSION)
    except Exception:
        return None


def _meter() -> Meter | None:
    return _provider(get_meter)


def _tracer() -> Tracer | None:
    return _provider(get_tracer)


def _histogram(name: str) -> Histogram | _NoOpInstrument:
    try:
        provider = _meter()
        if provider is None:
            return _NoOpInstrument()
        descriptions = {
            "anis.partners.request.duration": "Elapsed time for a Partner API request, in milliseconds.",
            "anis.partners.signature.duration": "Elapsed time to create a request signature, in milliseconds.",
        }
        return provider.create_histogram(name, unit="ms", description=descriptions.get(name, ""))
    except Exception:
        return _NoOpInstrument()


def _counter(name: str) -> Counter | _NoOpInstrument:
    try:
        provider = _meter()
        if provider is None:
            return _NoOpInstrument()
        descriptions = {
            "anis.partners.response.verification.failures": "Responses rejected by signature or content verification.",
            "anis.partners.order.outcomes": "Actionable order outcomes, excluding definitive not-placed results.",
            "anis.partners.signing_keys.fetches": "Network fetches of the published signing-key document.",
        }
        return provider.create_counter(name, description=descriptions.get(name, ""))
    except Exception:
        return _NoOpInstrument()


tracer = _tracer()
request_duration = _histogram("anis.partners.request.duration")
signature_duration = _histogram("anis.partners.signature.duration")
verification_failures = _counter("anis.partners.response.verification.failures")
order_outcomes = _counter("anis.partners.order.outcomes")
signing_key_fetches = _counter("anis.partners.signing_keys.fetches")
