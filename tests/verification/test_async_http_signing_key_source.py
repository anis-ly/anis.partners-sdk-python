"""Asynchronous HTTP signing-key fetch and shared-cache behavior."""

import asyncio
import json
import logging
import threading
import time

import httpx
import pytest

import anis_partners.verification.async_http_signing_key_source as async_key_source_module
from anis_partners.verification.async_http_signing_key_source import AsyncHttpSigningKeySource
from anis_partners.verification.http_signing_key_source import KeyDocumentCache


class MemoryKeyCache:
    """Stores published JSON like a host's multi-process cache."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        """Return a cached document if present."""
        return self.values.get(key)

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """Keep a document for the cache source's configured time to live."""
        self.values[key] = value


@pytest.mark.anyio
async def test_async_concurrent_first_use_fetches_once() -> None:
    """The asyncio lock coalesces simultaneous first calls into one HTTP request."""
    calls = 0
    call_guard = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        with call_guard:
            calls += 1
        time.sleep(0.02)
        return httpx.Response(200, json={"keys": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AsyncHttpSigningKeySource(client, "https://partners.anis.ly")
        await asyncio.gather(*(source.get() for _ in range(8)))
    assert calls == 1


@pytest.mark.anyio
async def test_async_second_instance_shared_hit_has_no_fetch_log_or_request(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shared-cache hit is neither a network fetch nor a fetch metric/log event."""
    calls = 0
    metric_calls: list[tuple[object, str, tuple[object, ...]]] = []
    cache: KeyDocumentCache = MemoryKeyCache()

    def capture_metric(instrument: object, method: str, *args: object) -> None:
        metric_calls.append((instrument, method, args))

    monkeypatch.setattr(async_key_source_module, "safe_metric", capture_metric)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=json.dumps({"keys": []}))

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as first,
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as second,
    ):
        await AsyncHttpSigningKeySource(first, "https://partners.anis.ly", cache=cache).get()
        assert len(metric_calls) == 1
        metric_calls.clear()
        caplog.set_level(logging.DEBUG, logger="anis_partners")
        caplog.clear()
        await AsyncHttpSigningKeySource(second, "https://partners.anis.ly", cache=cache).get()
    assert calls == 1
    assert metric_calls == []
    assert not any(getattr(record, "event_id", None) == 1005 for record in caplog.records)
    assert any(record.message == "signing keys read from the shared cache" for record in caplog.records)


@pytest.mark.anyio
async def test_async_shared_entry_expires_after_its_remaining_ten_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    cache = MemoryKeyCache()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"keys": []})

    ttl = 100
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        initial = AsyncHttpSigningKeySource(client, "https://partners.anis.ly", ttl, cache)
        await initial.get()
        entry = json.loads(cache.values[initial._cache_key])
        wall_now = int(time.time())
        entry["fetchedAt"] = wall_now - (ttl - 10)
        cache.values[initial._cache_key] = json.dumps(entry)
        wall = [wall_now]
        monotonic = [1000.0]
        monkeypatch.setattr(time, "time", lambda: wall[0])
        monkeypatch.setattr(time, "monotonic", lambda: monotonic[0])

        source = AsyncHttpSigningKeySource(client, "https://partners.anis.ly", ttl, cache)
        await source.get()
        assert calls == 1

        wall[0] += 11
        monotonic[0] += 10.1
        await source.get()

    assert calls == 2


@pytest.mark.anyio
async def test_async_unreadable_shared_entry_is_a_cache_miss() -> None:
    calls = 0
    cache = MemoryKeyCache()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"keys": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AsyncHttpSigningKeySource(client, "https://partners.anis.ly", cache=cache)
        cache.values[source._cache_key] = "not-json"
        await source.get()

    assert calls == 1


@pytest.mark.anyio
async def test_async_key_document_request_uses_identity_and_does_not_follow_redirects() -> None:
    """The async fetch keeps the exact unsigned key-document response and refuses redirect following."""
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(302, headers={"Location": "/replacement"}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        source = AsyncHttpSigningKeySource(client, "https://partners.anis.ly")
        with pytest.raises(httpx.HTTPStatusError):
            await source.get()

    assert len(observed) == 1
    assert observed[0].headers["Accept-Encoding"] == "identity"


@pytest.fixture
def anyio_backend() -> str:
    """Run async key-source tests on asyncio as required by the test contract."""
    return "asyncio"
