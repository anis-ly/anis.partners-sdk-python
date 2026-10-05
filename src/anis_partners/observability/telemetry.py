"""Stable SDK instrumentation names without requiring an OpenTelemetry SDK in the host."""

from collections.abc import Callable
from typing import TypeVar

from opentelemetry.metrics import Counter, Histogram, Meter, get_meter
from opentelemetry.trace import Tracer, get_tracer

INSTRUMENTATION_SCOPE = "anis_partners"
T = TypeVar("T")


class _NoOpInstrument:
    """Keep request handling available when host meter setup raises during SDK import."""

    def record(self, value: object, attributes: object = None) -> None:
        """Ignore a recording when no host instrument is available."""

    def add(self, value: object, attributes: object = None) -> None:
        """Ignore a count when no host instrument is available."""


def _provider(factory: Callable[[str], T]) -> T | None:
    try:
        return factory(INSTRUMENTATION_SCOPE)
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
        return provider.create_histogram(name, unit="ms")
    except Exception:
        return _NoOpInstrument()


def _counter(name: str) -> Counter | _NoOpInstrument:
    try:
        provider = _meter()
        if provider is None:
            return _NoOpInstrument()
        return provider.create_counter(name)
    except Exception:
        return _NoOpInstrument()


tracer = _tracer()
request_duration = _histogram("anis.partners.request.duration")
signature_duration = _histogram("anis.partners.signature.duration")
verification_failures = _counter("anis.partners.response.verification.failures")
order_outcomes = _counter("anis.partners.order.outcomes")
signing_key_fetches = _counter("anis.partners.signing_keys.fetches")
