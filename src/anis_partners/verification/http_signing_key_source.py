"""Fetch the unsigned public key document separately so verification does not depend on its own keys."""

from __future__ import annotations

import logging
import threading
import time

import httpx

from anis_partners._internal.key_document_cache import KeyDocumentCache as KeyDocumentCache
from anis_partners._internal.key_document_cache import (
    cache_key,
    decode_document,
    encode_document,
    expiry_from_fetch,
    read_cache,
    write_cache,
)
from anis_partners._internal.telemetry import safe_get_logger, safe_log, safe_metric
from anis_partners.errors.base import KeyDocumentUnavailableError
from anis_partners.observability.telemetry import signing_key_fetches
from anis_partners.options import ClientOptions
from anis_partners.verification.partner_jwk import SigningKeySet


class HttpSigningKeySource:
    """Fetch keys over HTTPS so every verified response chains to a protected authority."""

    PATH = "/.well-known/partner-signing-keys.json"

    def __init__(
        self,
        client: httpx.Client,
        authority: str,
        cache_seconds: int = 600,
        cache: KeyDocumentCache | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        """Use the host transport while validating the trust root before any key request can be sent."""
        self._client = client
        self._authority = ClientOptions(authority).authority
        if type(cache_seconds) is not int or cache_seconds <= 0:
            raise ValueError("cache_seconds must be a positive integer number of seconds.")
        self._ttl = cache_seconds
        self._timeout = timeout_seconds
        self._cache = cache
        self._cache_key = cache_key(self._authority)
        self._lock = threading.Lock()
        self._document: SigningKeySet | None = None
        self._expires_at = 0.0
        self._logger = safe_get_logger("anis_partners")

    def get(self) -> SigningKeySet:
        """Return fresh keys without waiting for a simultaneous rotation fetch."""
        document = self._document
        if document is not None and time.monotonic() < self._expires_at:
            return document
        reason = "expired" if document is not None else "first-use"
        shared = read_cache(self._cache, self._cache_key, self._logger)
        if shared is not None:
            cached = decode_document(shared, int(time.time()), self._ttl)
            if cached is not None:
                document, fetched_at = cached
                with self._lock:
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
        with self._lock:
            document = self._document
            if document is not None and time.monotonic() < self._expires_at:
                return document
            if document is not None:
                reason = "expired"
            return self._fetch_locked(reason)

    def refresh(self, previous: SigningKeySet | None = None) -> SigningKeySet:
        """Fetch after an unknown key, reusing a rotation document fetched while this caller waited."""
        with self._lock:
            current = self._document
            if (
                previous is not None
                and current is not None
                and current is not previous
                and time.monotonic() < self._expires_at
            ):
                return current
            return self._fetch_locked("refresh")

    def _fetch_locked(self, reason: str) -> SigningKeySet:
        try:
            response = self._client.get(
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
        write_cache(self._cache, self._cache_key, encode_document(raw, fetched_at), self._ttl, self._logger)
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
        return document
