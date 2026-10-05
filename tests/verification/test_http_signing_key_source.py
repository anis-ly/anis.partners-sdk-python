"""HTTP signing-key fetch cache, refresh, and concurrent caller behavior."""

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

import anis_partners.verification.http_signing_key_source as key_source_module
from anis_partners.verification.http_signing_key_source import HttpSigningKeySource


class SharedCache:
    """Minimal host-provided document cache for the sharing test."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        """Read a cached document."""
        return self.values.get(key)

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """Store a cached document."""
        self.values[key] = value


def test_fetch_cache_and_refresh_use_expected_requests() -> None:
    """First use fetches once, TTL expiry refetches, and explicit refresh always fetches."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"keys": []})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        source = HttpSigningKeySource(client, "https://partners.anis.ly", cache_seconds=1)
        source.get()
        source.get()
        assert calls == 1
        time.sleep(1.01)
        source.get()
        source.refresh()
    assert calls == 3


def test_concurrent_first_use_fetches_only_once() -> None:
    """A lock coalesces concurrent first callers into one HTTP request."""
    calls = 0
    guard = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        with guard:
            calls += 1
        time.sleep(0.03)
        return httpx.Response(200, json={"keys": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        source = HttpSigningKeySource(client, "https://partners.anis.ly")
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: source.get(), range(8)))
    assert calls == 1


def test_second_instance_reads_shared_document_without_fetch_log_or_http_request(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shared-cache hit is neither a network fetch nor a fetch metric/log event."""
    calls = 0
    metric_calls: list[tuple[object, str, tuple[object, ...]]] = []
    shared = SharedCache()

    def capture_metric(instrument: object, method: str, *args: object) -> None:
        metric_calls.append((instrument, method, args))

    monkeypatch.setattr(key_source_module, "safe_metric", capture_metric)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=json.dumps({"keys": []}))

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as first,
        httpx.Client(transport=httpx.MockTransport(handler)) as second,
    ):
        HttpSigningKeySource(first, "https://partners.anis.ly", cache=shared).get()
        assert len(metric_calls) == 1
        metric_calls.clear()
        caplog.set_level(logging.DEBUG, logger="anis_partners")
        caplog.clear()
        HttpSigningKeySource(second, "https://PARTNERS.anis.ly", cache=shared).get()
    assert calls == 1
    assert metric_calls == []
    assert not any(getattr(record, "event_id", None) == 1005 for record in caplog.records)
    assert any(record.message == "signing keys read from the shared cache" for record in caplog.records)


def test_shared_entry_expires_after_its_remaining_ten_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    shared = SharedCache()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"keys": []})

    ttl = 100
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        initial = HttpSigningKeySource(client, "https://partners.anis.ly", ttl, shared)
        initial.get()
        entry = json.loads(shared.values[initial._cache_key])
        wall_now = int(time.time())
        entry["fetchedAt"] = wall_now - (ttl - 10)
        shared.values[initial._cache_key] = json.dumps(entry)
        wall = [wall_now]
        monotonic = [1000.0]
        monkeypatch.setattr(time, "time", lambda: wall[0])
        monkeypatch.setattr(time, "monotonic", lambda: monotonic[0])

        source = HttpSigningKeySource(client, "https://partners.anis.ly", ttl, shared)
        source.get()
        assert calls == 1

        wall[0] += 11
        monotonic[0] += 10.1
        source.get()

    assert calls == 2


def test_unreadable_shared_entry_is_a_cache_miss() -> None:
    calls = 0
    shared = SharedCache()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"keys": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        source = HttpSigningKeySource(client, "https://partners.anis.ly", cache=shared)
        shared.values[source._cache_key] = "not-json"
        source.get()

    assert calls == 1


def test_key_document_request_uses_identity_and_does_not_follow_redirects() -> None:
    """Fetch the exact key-document response without decoding content or hiding a redirected authority path."""
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(302, headers={"Location": "/replacement"}, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        source = HttpSigningKeySource(client, "https://partners.anis.ly")
        try:
            source.get()
        except httpx.HTTPStatusError:
            pass
        else:
            raise AssertionError("A key-document redirect must remain an ordinary response.")

    assert len(observed) == 1
    assert observed[0].headers["Accept-Encoding"] == "identity"
