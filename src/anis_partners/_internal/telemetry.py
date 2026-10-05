"""Isolate host-provided diagnostics so failures cannot replace SDK business results."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager, suppress

from opentelemetry.trace import Span, SpanKind, Status, Tracer


class _NoOpSpan:
    """Provide an inert span when a host tracer is unavailable or failing."""

    def set_attribute(self, name: str, value: object) -> None:
        """Ignore an attribute when no usable span exists."""

    def set_status(self, status: object) -> None:
        """Ignore a status when no usable span exists."""


class _SafeSpan:
    """Swallow only failures from span mutation methods supplied by a host tracer."""

    def __init__(self, span: Span) -> None:
        self._span = span

    def set_attribute(self, name: str, value: object) -> None:
        """Set one bounded SDK attribute without allowing exporter code to affect the call."""
        with suppress(Exception):
            self._span.set_attribute(name, value)

    def set_status(self, status: Status) -> None:
        """Set a bounded SDK status without allowing exporter code to affect the call."""
        with suppress(Exception):
            self._span.set_status(status)


@contextmanager
def safe_span(tracer: Tracer | None, name: str, kind: SpanKind) -> Iterator[_SafeSpan | _NoOpSpan]:
    """Create a span with automatic exception recording disabled and isolate tracer failures."""
    try:
        if tracer is None:
            raise RuntimeError("No host tracer is available.")
        manager = tracer.start_as_current_span(
            name,
            kind=kind,
            record_exception=False,
            set_status_on_exception=False,
        )
        span = manager.__enter__()
    except Exception:
        yield _NoOpSpan()
        return

    try:
        yield _SafeSpan(span)
    except BaseException as exc:
        with suppress(Exception):
            manager.__exit__(type(exc), exc, exc.__traceback__)
        raise
    else:
        with suppress(Exception):
            manager.__exit__(None, None, None)


def safe_metric(instrument: object, method: str, *args: object) -> None:
    """Call a host metric instrument without letting its failure alter request handling."""
    with suppress(Exception):
        getattr(instrument, method)(*args)


def safe_get_logger(name: str) -> logging.Logger | None:
    """Get the host logger when available, otherwise leave diagnostics disabled."""
    try:
        return logging.getLogger(name)
    except Exception:
        return None


def safe_log(logger: logging.Logger | None, level: int, message: str, **fields: object) -> None:
    """Emit structured fields while swallowing errors from an application logger."""
    if logger is None:
        return
    with suppress(Exception):
        event_id = fields.pop("event_id", None)
        logger.log(level, message, extra={"event_id": event_id, **fields})
