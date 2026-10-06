"""Fetch the unsigned public key document asynchronously without blocking verification."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from anis_partners._internal.key_document_cache import (
    AsyncKeyDocumentCache,
    KeyDocumentCache,
    cache_key,
    decode_document,
    encode_document,
    expiry_from_fetch,
    read_async_cache,
    write_async_cache,
)
from anis_partners._internal.telemetry import safe_get_logger, safe_log, safe_metric
from anis_partners.errors.base import KeyDocumentUnavailableError
from anis_partners.observability.telemetry import signing_key_fetches
from anis_partners.options import ClientOptions
from anis_partners.verification.partner_jwk import SigningKeySet


class AsyncHttpSigningKeySource:
    """Coalesce network fetches while serving cached reads without waiting behind a rotation request."""

    PATH = "/.well-known/partner-signing-keys.json"

    def __init__(
        self,
        client: httpx.AsyncClient,
        authority: str,
        cache_seconds: int = 600,
        cache: KeyDocumentCache | AsyncKeyDocumentCache | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        """Validate the key-document trust root and retain either sync or async host cache adapters."""
        self._client = client
        self._authority = ClientOptions(authority).authority
        if type(cache_seconds) is not int or cache_seconds <= 0:
            raise ValueError("cache_seconds must be a positive integer number of seconds.")
        self._ttl = cache_seconds
        self._timeout = timeout_seconds
        self._cache = cache
        self._cache_key = cache_key(self._authority)
        self._lock = asyncio.Lock()
        self._document: SigningKeySet | None = None
        self._expires_at = 0.0
        self._logger = safe_get_logger("anis_partners")

    async def get(self) -> SigningKeySet:
        """Serve an unexpired local/shared document first; only network misses join the fetch lock."""
        document = self._document
        if document is not None and time.monotonic() < self._expires_at:
            return document
        reason = "expired" if document is not None else "first-use"
        shared = await read_async_cache(self._cache, self._cache_key, self._logger)
        if shared is not None:
            cached = decode_document(shared, int(time.time()), self._ttl)
            if cached is not None:
                document, fetched_at = cached
                async with self._lock:
                    current = self._document
                    if current is not None and time.monotonic() < self._expires_at:
                        return current
                    self._document = document
                    self._expires_at = expiry_from_fetch(fetched_at, self._ttl)
                safe_log(
                    self._logger,
                    logging.DEBUG,
                    "signing keys read from the shared cache",
                    key_count=len(document.keys),
                )
                return document
        async with self._lock:
            document = self._document
            if document is not None and time.monotonic() < self._expires_at:
                return document
            if document is not None:
                reason = "expired"
            document, raw, fetched_at = await self._fetch_locked(reason)
        await write_async_cache(self._cache, self._cache_key, encode_document(raw, fetched_at), self._ttl, self._logger)
        return document

    async def refresh(self, previous: SigningKeySet | None = None) -> SigningKeySet:
        """Reuse a newer document fetched by a caller that completed while this task waited."""
        async with self._lock:
            current = self._document
            if (
                previous is not None
                and current is not None
                and current is not previous
                and time.monotonic() < self._expires_at
            ):
                return current
            document, raw, fetched_at = await self._fetch_locked("refresh")
        await write_async_cache(self._cache, self._cache_key, encode_document(raw, fetched_at), self._ttl, self._logger)
        return document

    async def _fetch_locked(self, reason: str) -> tuple[SigningKeySet, str, int]:
        try:
            response = await self._client.get(
                self._authority + self.PATH,
                headers={"Accept-Encoding": "identity"},
                follow_redirects=False,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            raise KeyDocumentUnavailableError("Fetching the Anis signing-key document timed out.", "timeout") from None
        except httpx.HTTPStatusError:
            raise KeyDocumentUnavailableError("Anis returned an unsuccessful signing-key document response.") from None
        except httpx.TransportError:
            raise KeyDocumentUnavailableError("The Anis signing-key document could not be fetched.") from None
        except httpx.HTTPError:
            raise KeyDocumentUnavailableError("The Anis signing-key document could not be read.") from None
        try:
            raw = response.text
        except httpx.HTTPError:
            raise KeyDocumentUnavailableError("The Anis signing-key document could not be decoded.") from None
        try:
            document = SigningKeySet.from_json(raw)
        except Exception:
            raise KeyDocumentUnavailableError("The Anis signing-key document is malformed.") from None
        fetched_at = int(time.time())
        self._document = document
        self._expires_at = time.monotonic() + self._ttl
        safe_metric(signing_key_fetches, "add", 1, {"anis.fetch.reason": reason})
        safe_log(
            self._logger,
            logging.INFO,
            "Fetched the Anis signing-key document (%s): %s published key versions.",
            reason,
            len(document.keys),
            event_id=1005,
            reason=reason,
            key_count=len(document.keys),
        )
        return document, raw, fetched_at
