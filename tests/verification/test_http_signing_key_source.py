"""HTTP signing-key fetch cache, refresh, and concurrent caller behavior."""

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest

import anis_partners.verification.http_signing_key_source as key_source_module
from anis_partners._internal.key_document_cache import decode_document
from anis_partners.errors import KeyDocumentUnavailableError
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


def test_fetch_cache_and_refresh_use_expected_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """First use fetches once, TTL expiry refetches, and explicit refresh always fetches."""
    calls = 0
    monotonic = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: monotonic[0])

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
        monotonic[0] += 1.01
        source.get()
        source.refresh()
    assert calls == 3


def test_network_key_fetch_event_is_info_with_reason_and_key_count(caplog: pytest.LogCaptureFixture) -> None:
    """Give operators a visible network-fetch event with bounded refresh reason and published-key count."""
    caplog.set_level(logging.DEBUG, logger="anis_partners")
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"keys": []}))) as client:
        HttpSigningKeySource(client, "https://partners.anis.ly").get()
    fetched = next(record for record in caplog.records if getattr(record, "event_id", None) == 1005)
    assert fetched.levelno == logging.INFO
    assert fetched.__dict__["reason"] == "first-use"
    assert fetched.__dict__["key_count"] == 0
    assert "first-use" in fetched.getMessage()
    assert "0 published key versions" in fetched.getMessage()


def test_key_source_rejects_non_loopback_http_authority() -> None:
    """Keep the unsigned key document on HTTPS so an intermediary cannot choose which responses verify."""
    with (
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client,
        pytest.raises(ValueError, match="HTTPS"),
    ):
        HttpSigningKeySource(client, "http://partners.example")


@pytest.mark.parametrize(
    ("failure", "error_type"),
    [
        ("status", "connection"),
        ("transport", "connection"),
        ("timeout", "timeout"),
        ("malformed", "connection"),
        ("gzip", "connection"),
    ],
)
def test_key_document_fetch_failures_use_the_sdk_error_and_bounded_transport_reason(
    failure: str, error_type: str
) -> None:
    """Expose unusable key documents through the SDK error type with a safe connection or timeout classification."""

    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "status":
            return httpx.Response(503, request=request)
        if failure == "transport":
            raise httpx.ConnectError("offline", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        if failure == "gzip":
            return httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=b"corrupt gzip", request=request)
        return httpx.Response(200, json={"keys": "malformed"}, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        source = HttpSigningKeySource(client, "https://partners.anis.ly")
        with pytest.raises(KeyDocumentUnavailableError) as caught:
            source.get()
    assert caught.value.error_type == error_type
    assert caught.value.__cause__ is None


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


def test_future_dated_shared_document_is_a_cache_miss() -> None:
    """Refuse shared documents timestamped beyond allowed clock skew before they can become trusted keys."""
    entry = json.dumps({"document": '{"keys": []}', "fetchedAt": 1_061})
    assert decode_document(entry, now=1_000, ttl_seconds=600) is None


def test_shared_cache_outages_are_best_effort_for_reads_and_writes() -> None:
    """Use the fetched key document even when the optional host cache is unavailable."""

    class UnavailableCache:
        def get(self, key: str) -> str | None:
            raise ConnectionError("cache down")

        def set(self, key: str, value: str, ttl_seconds: int) -> None:
            raise ConnectionError("cache down")

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"keys": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        source = HttpSigningKeySource(client, "https://partners.anis.ly", cache=UnavailableCache())
        assert source.get().keys == ()
        assert source.get().keys == ()
    assert calls == 1


def test_concurrent_refresh_waiters_reuse_the_new_document() -> None:
    """One rotation fetch serves every verifier that was waiting on the same old key set."""
    calls = 0
    entered = Event()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls > 1:
            entered.set()
            time.sleep(0.03)
        return httpx.Response(200, json={"keys": [{"kid": str(calls), "x": "AA", "y": "AA"}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        source = HttpSigningKeySource(client, "https://partners.anis.ly")
        old = source.get()
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(source.refresh, old) for _ in range(8)]
            assert entered.wait(1)
            docs = [future.result() for future in futures]
    assert calls == 2
    assert all(document is docs[0] for document in docs)


def test_cached_reads_do_not_wait_behind_a_refresh_fetch() -> None:
    """Keep ordinary response verification responsive while a rotation refresh is in flight."""
    refresh_entered = Event()
    release_refresh = Event()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls > 1:
            refresh_entered.set()
            release_refresh.wait(2)
        return httpx.Response(200, json={"keys": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        source = HttpSigningKeySource(client, "https://partners.anis.ly")
        cached = source.get()
        with ThreadPoolExecutor(max_workers=2) as pool:
            refresh = pool.submit(source.refresh, cached)
            assert refresh_entered.wait(1)
            assert source.get() is cached
            release_refresh.set()
            refresh.result()


def test_shared_cache_names_are_isolated_by_authority() -> None:
    """Prevent one deployment from authenticating answers with another authority's keys."""
    cache = SharedCache()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url.host))
        return httpx.Response(200, json={"keys": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        HttpSigningKeySource(client, "https://partners-one.anis.ly", cache=cache).get()
        HttpSigningKeySource(client, "https://partners-two.anis.ly", cache=cache).get()
    assert calls == ["partners-one.anis.ly", "partners-two.anis.ly"]


def test_http_key_source_only_allows_loopback_plain_http() -> None:
    """Protect the unsigned trust document even when hosts construct the source directly."""
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"keys": []}))) as client:
        with pytest.raises(ValueError, match="HTTPS"):
            HttpSigningKeySource(client, "http://partners.anis.ly")
        HttpSigningKeySource(client, "http://127.0.0.1:8080")


def test_key_document_request_uses_identity_and_does_not_follow_redirects() -> None:
    """Fetch the exact key-document response without decoding content or hiding a redirected authority path."""
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(302, headers={"Location": "/replacement"}, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        source = HttpSigningKeySource(client, "https://partners.anis.ly")
        with pytest.raises(KeyDocumentUnavailableError, match="unsuccessful signing-key"):
            source.get()

    assert len(observed) == 1
    assert observed[0].headers["Accept-Encoding"] == "identity"
