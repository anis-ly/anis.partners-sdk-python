"""Fetch the unsigned public key document separately so verification does not depend on its own keys."""

import asyncio
import hashlib
import logging
import time

import httpx

from anis_partners._internal.telemetry import safe_get_logger, safe_log, safe_metric
from anis_partners.observability.telemetry import signing_key_fetches
from anis_partners.verification.http_signing_key_source import (
    KeyDocumentCache,
    _decode_shared_document,
    _encode_shared_document,
)
from anis_partners.verification.partner_jwk import SigningKeySet


class AsyncHttpSigningKeySource:
    """Coalesce async key fetches and cache rotation data so concurrent responses do not stampede Anis."""

    PATH = "/.well-known/partner-signing-keys.json"

    def __init__(
        self,
        client: httpx.AsyncClient,
        authority: str,
        cache_seconds: int = 600,
        cache: KeyDocumentCache | None = None,
    ) -> None:
        """Use the host's async transport and authority so key retrieval follows its configured network path."""
        self._client = client
        self._authority = authority.rstrip("/")
        self._ttl = cache_seconds
        self._cache = cache
        self._cache_key = "anis-partners.signing-keys." + hashlib.sha256(authority.lower().encode()).hexdigest()
        self._lock = asyncio.Lock()
        self._document: SigningKeySet | None = None
        self._expires_at = 0.0
        self._logger = safe_get_logger("anis_partners")

    async def get(self) -> SigningKeySet:
        """Reuse unexpired keys and serialize fetches so concurrent first responses issue one request."""
        async with self._lock:
            if self._document is not None and time.monotonic() < self._expires_at:
                return self._document
            reason = "expired" if self._document is not None else "first-use"
            return await self._fetch_locked(reason)

    async def refresh(self) -> SigningKeySet:
        """Fetch once after an unknown key so rotation recovers without unbounded retry traffic."""
        async with self._lock:
            return await self._fetch_locked("refresh")

    async def _fetch_locked(self, reason: str) -> SigningKeySet:
        expired = reason == "expired"
        if self._cache is not None:
            raw = self._cache.get(self._cache_key)
            if raw is not None and reason != "refresh":
                cached = _decode_shared_document(raw, int(time.time()), self._ttl)
                if cached is not None:
                    document, fetched_at = cached
                    self._document = document
                    remaining = fetched_at + self._ttl - int(time.time())
                    self._expires_at = time.monotonic() + remaining
                    safe_log(
                        self._logger,
                        logging.DEBUG,
                        "signing keys read from the shared cache",
                        count=len(document.keys),
                    )
                    return document
                expired = True
        if reason != "refresh" and expired:
            reason = "expired"
        response = await self._client.get(
            self._authority + self.PATH,
            headers={"Accept-Encoding": "identity"},
            follow_redirects=False,
        )
        response.raise_for_status()
        raw = response.text
        document = SigningKeySet.from_json(raw)
        fetched_at = int(time.time())
        self._document = document
        self._expires_at = time.monotonic() + self._ttl
        if self._cache is not None:
            self._cache.set(self._cache_key, _encode_shared_document(raw, fetched_at), self._ttl)
        safe_metric(signing_key_fetches, "add", 1, {"anis.fetch.reason": reason})
        safe_log(
            self._logger,
            logging.DEBUG,
            "signing keys fetched",
            event_id=1005,
            reason=reason,
            count=len(document.keys),
        )
        return document
