"""Asynchronous HTTP signing-key fetch and shared-cache behavior."""

import asyncio
import json
import logging
import threading
import time

import httpx
import pytest

import anis_partners._internal.key_document_cache as key_document_cache_module
import anis_partners.verification.async_http_signing_key_source as async_key_source_module
from anis_partners.errors import KeyDocumentUnavailableError
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


class AsyncMemoryKeyCache:
    """Store cache values through genuinely awaitable hooks used by async host services."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self.values[key] = value


@pytest.mark.anyio
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
async def test_async_key_document_fetch_failures_use_the_sdk_error_and_bounded_transport_reason(
    failure: str, error_type: str
) -> None:
    """Use one public SDK error for HTTP, transport, timeout, and malformed async key documents."""

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

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AsyncHttpSigningKeySource(client, "https://partners.anis.ly")
        with pytest.raises(KeyDocumentUnavailableError) as caught:
            await source.get()
    assert caught.value.error_type == error_type
    assert caught.value.__cause__ is None


@pytest.mark.anyio
async def test_async_concurrent_first_use_fetches_once() -> None:
    """The asyncio lock coalesces simultaneous first calls into one HTTP request."""
    calls = 0
    call_guard = threading.Lock()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        with call_guard:
            calls += 1
        await asyncio.sleep(0.02)
        return httpx.Response(200, json={"keys": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AsyncHttpSigningKeySource(client, "https://partners.anis.ly")
        await asyncio.gather(*(source.get() for _ in range(8)))
    assert calls == 1


@pytest.mark.anyio
async def test_async_shared_cache_outages_are_best_effort_for_reads_and_writes() -> None:
    """Run async verification through the network if a shared cache hook raises."""

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

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AsyncHttpSigningKeySource(client, "https://partners.anis.ly", cache=UnavailableCache())
        assert (await source.get()).keys == ()
        assert (await source.get()).keys == ()
    assert calls == 1


@pytest.mark.anyio
async def test_async_refresh_waiters_share_the_rotation_fetch() -> None:
    """Let tasks interleave at network waits while ensuring only one rotation document is fetched."""
    calls = 0
    refresh_entered = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls > 1:
            refresh_entered.set()
            await asyncio.sleep(0.03)
        return httpx.Response(200, json={"keys": [{"kid": str(calls), "x": "AA", "y": "AA"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AsyncHttpSigningKeySource(client, "https://partners.anis.ly")
        old = await source.get()
        tasks = [asyncio.create_task(source.refresh(old)) for _ in range(8)]
        await refresh_entered.wait()
        docs = await asyncio.gather(*tasks)
    assert calls == 2
    assert all(document is docs[0] for document in docs)


@pytest.mark.anyio
async def test_async_cached_get_does_not_wait_behind_rotation_fetch() -> None:
    """Return locally cached keys while the async lock is held by a network refresh."""
    refresh_entered = asyncio.Event()
    release_refresh = asyncio.Event()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls > 1:
            refresh_entered.set()
            await release_refresh.wait()
        return httpx.Response(200, json={"keys": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AsyncHttpSigningKeySource(client, "https://partners.anis.ly")
        cached = await source.get()
        refresh = asyncio.create_task(source.refresh(cached))
        await refresh_entered.wait()
        assert await asyncio.wait_for(source.get(), 0.05) is cached
        release_refresh.set()
        await refresh


@pytest.mark.anyio
async def test_async_synchronous_cache_does_not_block_the_event_loop() -> None:
    """Run a blocking host cache in a worker thread so unrelated async tasks keep moving."""
    progressed = asyncio.Event()

    class SlowCache(MemoryKeyCache):
        def get(self, key: str) -> str | None:
            time.sleep(0.05)
            return super().get(key)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keys": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AsyncHttpSigningKeySource(client, "https://partners.anis.ly", cache=SlowCache())
        pending = asyncio.create_task(source.get())
        asyncio.get_running_loop().call_later(0.005, progressed.set)
        await asyncio.wait_for(progressed.wait(), 0.03)
        await pending


@pytest.mark.anyio
async def test_async_native_cache_hooks_are_awaited_and_shared() -> None:
    """Use async cache adapters directly so cache-backed hosts can avoid blocking thread pools."""
    calls = 0
    cache = AsyncMemoryKeyCache()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"keys": []})

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as first,
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as second,
    ):
        await AsyncHttpSigningKeySource(first, "https://partners.anis.ly", cache=cache).get()
        await AsyncHttpSigningKeySource(second, "https://partners.anis.ly", cache=cache).get()
    assert calls == 1


@pytest.mark.anyio
async def test_async_never_settling_cache_read_does_not_block_key_fetch() -> None:
    """Treat a cache read that exceeds its two-second bound as a miss so verification can fetch keys."""

    class HangingRead:
        async def get(self, key: str) -> str | None:
            await asyncio.Event().wait()
            return None

        async def set(self, key: str, value: str, ttl_seconds: int) -> None:
            return None

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"keys": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AsyncHttpSigningKeySource(client, "https://partners.anis.ly", cache=HangingRead())
        assert (await source.get()).keys == ()
    assert calls == 1


@pytest.mark.anyio
async def test_async_never_settling_cache_write_does_not_lose_fetched_document() -> None:
    """Return a fetched public key set even when an optional cache write never settles."""

    class HangingWrite:
        async def get(self, key: str) -> str | None:
            return None

        async def set(self, key: str, value: str, ttl_seconds: int) -> None:
            await asyncio.Event().wait()

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"keys": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AsyncHttpSigningKeySource(client, "https://partners.anis.ly", cache=HangingWrite())
        assert (await source.get()).keys == ()
    assert calls == 1


@pytest.mark.anyio
async def test_async_cache_that_swallows_cancellation_cannot_hold_fetch_or_refresh_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Abandon cancellation-resistant cache reads and writes so key verification and fresh reads can proceed."""
    monkeypatch.setattr(key_document_cache_module, "ASYNC_CACHE_TIMEOUT_SECONDS", 0.02)
    read_started = asyncio.Event()
    write_started = asyncio.Event()
    release = asyncio.Event()

    class CancellationResistantCache:
        async def get(self, key: str) -> str | None:
            read_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
            return None

        async def set(self, key: str, value: str, ttl_seconds: int) -> None:
            write_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keys": []}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AsyncHttpSigningKeySource(client, "https://partners.anis.ly", cache=CancellationResistantCache())
        pending = asyncio.create_task(source.get())
        await asyncio.wait_for(read_started.wait(), 0.2)
        document = await asyncio.wait_for(pending, 0.2)
        await asyncio.wait_for(write_started.wait(), 0.2)
        assert await asyncio.wait_for(source.get(), 0.05) is document
        release.set()
        await asyncio.sleep(0)


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
        with pytest.raises(KeyDocumentUnavailableError, match="unsuccessful signing-key"):
            await source.get()

    assert len(observed) == 1
    assert observed[0].headers["Accept-Encoding"] == "identity"
