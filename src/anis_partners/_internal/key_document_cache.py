"""Best-effort shared key-cache encoding used by both transports."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol, TypeVar, cast

from anis_partners._internal.telemetry import safe_log

if TYPE_CHECKING:
    from anis_partners.verification.partner_jwk import SigningKeySet

T = TypeVar("T")
ASYNC_CACHE_TIMEOUT_SECONDS = 2


class KeyDocumentCache(Protocol):
    """Share public signing-key documents without making verification depend on cache availability."""

    def get(self, key: str) -> str | None:
        """Return an encoded document or a miss."""

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """Store an encoded document for no longer than its configured lifetime."""


class AsyncKeyDocumentCache(Protocol):
    """Allow hosts to use an async cache without blocking the event loop."""

    async def get(self, key: str) -> str | None:
        """Return an encoded document or a miss."""

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """Store an encoded document for no longer than its configured lifetime."""


def cache_key(authority: str) -> str:
    """Normalize authority spellings so equivalent endpoints share one cache entry."""
    normalized = authority.lower().rstrip("/")
    return "anis_partners_keys_" + hashlib.sha256(normalized.encode()).hexdigest()[:32]


def encode_document(document: str, fetched_at: int) -> str:
    """Keep the original fetch time so another process cannot extend an old entry's trust window."""
    return json.dumps({"document": document, "fetchedAt": fetched_at}, separators=(",", ":"))


def decode_document(raw: object, now: int, ttl_seconds: int) -> tuple[SigningKeySet, int] | None:
    """Treat malformed, expired, or implausibly future-dated values as cache misses."""
    try:
        from anis_partners.verification.partner_jwk import SigningKeySet

        if not isinstance(raw, str):
            return None
        entry = json.loads(raw)
        if not isinstance(entry, dict):
            return None
        document = entry.get("document")
        fetched_at = entry.get("fetchedAt")
        if not isinstance(document, str) or type(fetched_at) is not int:
            return None
        age = now - fetched_at
        if age < -60 or age >= ttl_seconds:
            return None
        return SigningKeySet.from_json(document), fetched_at
    except Exception:
        return None


def read_cache(cache: KeyDocumentCache | None, key: str, logger: logging.Logger | None) -> str | None:
    """Fail open on optional cache outages so Anis remains the authority for key retrieval."""
    if cache is None:
        return None
    try:
        return cache.get(key)
    except Exception:
        safe_log(logger, logging.WARNING, "shared signing-key cache read failed")
        return None


def write_cache(
    cache: KeyDocumentCache | None, key: str, value: str, ttl_seconds: int, logger: logging.Logger | None
) -> None:
    """Ignore cache write failures because the fetched document is already usable in memory."""
    if cache is None:
        return
    try:
        cache.set(key, value, ttl_seconds)
    except Exception:
        safe_log(logger, logging.WARNING, "shared signing-key cache write failed")


async def call_async_cache(callback: Callable[..., object], *args: object, timeout_seconds: float = 2) -> object:
    """Run cache adapters off-lock and abandon unresponsive hooks without waiting for cancellation."""

    async def invoke() -> object:
        if inspect.iscoroutinefunction(callback):
            return await cast(Awaitable[object], callback(*args))
        result = await asyncio.to_thread(callback, *args)
        if inspect.isawaitable(result):
            return await cast(Awaitable[object], result)
        return result

    def consume_abandoned(task: asyncio.Task[object]) -> None:
        if not task.cancelled():
            task.exception()

    task = asyncio.create_task(invoke())
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout_seconds)
        if task not in done:
            task.cancel()
            task.add_done_callback(consume_abandoned)
            raise TimeoutError("The shared signing-key cache did not respond in time.")
        return task.result()
    except BaseException:
        if not task.done():
            task.cancel()
            task.add_done_callback(consume_abandoned)
        raise


async def read_async_cache(
    cache: KeyDocumentCache | AsyncKeyDocumentCache | None, key: str, logger: logging.Logger | None
) -> str | None:
    """Treat cache errors and slow cache calls as misses while leaving the fetch flight available."""
    if cache is None:
        return None
    try:
        value = await call_async_cache(cache.get, key, timeout_seconds=ASYNC_CACHE_TIMEOUT_SECONDS)
        return value if isinstance(value, str) else None
    except Exception:
        safe_log(logger, logging.WARNING, "shared signing-key cache read failed")
        return None


async def write_async_cache(
    cache: KeyDocumentCache | AsyncKeyDocumentCache | None,
    key: str,
    value: str,
    ttl_seconds: int,
    logger: logging.Logger | None,
) -> None:
    """Bound optional cache latency and ignore failed writes after a successful key fetch."""
    if cache is None:
        return
    try:
        await call_async_cache(cache.set, key, value, ttl_seconds, timeout_seconds=ASYNC_CACHE_TIMEOUT_SECONDS)
    except Exception:
        safe_log(logger, logging.WARNING, "shared signing-key cache write failed")


def expiry_from_fetch(fetched_at: int, ttl_seconds: int) -> float:
    """Convert shared wall-clock age into a local monotonic deadline."""
    remaining = max(0, fetched_at + ttl_seconds - int(time.time()))
    return time.monotonic() + remaining
