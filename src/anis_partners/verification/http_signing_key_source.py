"""Fetch the unsigned public key document separately so verification does not depend on its own keys."""

import hashlib
import json
import logging
import threading
import time
from typing import Protocol

import httpx

from anis_partners._internal.telemetry import safe_get_logger, safe_log, safe_metric
from anis_partners.observability.telemetry import signing_key_fetches
from anis_partners.verification.partner_jwk import SigningKeySet


class KeyDocumentCache(Protocol):
    """Share key documents across workers so each process does not fetch the same rotation data."""

    def get(self, key: str) -> str | None:
        """Return shared JSON or a miss so workers can reuse the same bounded key document."""

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """Bound shared staleness so rotated keys do not remain trusted indefinitely."""


def _encode_shared_document(document: str, fetched_at: int) -> str:
    """Keep the original signed-key JSON beside its original fetch time for shared workers."""
    return json.dumps({"document": document, "fetchedAt": fetched_at}, separators=(",", ":"))


def _decode_shared_document(raw: str, now: int, ttl_seconds: int) -> tuple[SigningKeySet, int] | None:
    """Reject stale or malformed shared entries and retain the timestamp needed for local expiry."""
    try:
        entry = json.loads(raw)
        if not isinstance(entry, dict):
            return None
        document = entry.get("document")
        fetched_at = entry.get("fetchedAt")
        if not isinstance(document, str) or type(fetched_at) is not int:
            return None
        age = now - fetched_at
        if age < 0 or age >= ttl_seconds:
            return None
        return SigningKeySet.from_json(document), fetched_at
    except (TypeError, ValueError):
        return None


class HttpSigningKeySource:
    """Fetch the unsigned key document outside verification so there is no recursive trust dependency."""

    PATH = "/.well-known/partner-signing-keys.json"

    def __init__(
        self,
        client: httpx.Client,
        authority: str,
        cache_seconds: int = 600,
        cache: KeyDocumentCache | None = None,
    ) -> None:
        """Use the host's HTTP transport and authority so key retrieval follows its configured network path."""
        self._client = client
        self._authority = authority.rstrip("/")
        self._ttl = cache_seconds
        self._cache = cache
        self._cache_key = "anis-partners.signing-keys." + hashlib.sha256(authority.lower().encode()).hexdigest()
        self._lock = threading.Lock()
        self._document: SigningKeySet | None = None
        self._expires_at = 0.0
        self._logger = safe_get_logger("anis_partners")

    def get(self) -> SigningKeySet:
        """Reuse unexpired keys and serialize fetches so concurrent first responses issue one request."""
        with self._lock:
            if self._document is not None and time.monotonic() < self._expires_at:
                return self._document
            reason = "expired" if self._document is not None else "first-use"
            return self._fetch_locked(reason)

    def refresh(self) -> SigningKeySet:
        """Fetch once after an unknown key so rotation recovers without unbounded retry traffic."""
        with self._lock:
            return self._fetch_locked("refresh")

    def _fetch_locked(self, reason: str) -> SigningKeySet:
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
        response = self._client.get(
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
