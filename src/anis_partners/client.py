"""Synchronous and asynchronous verified clients over caller-controlled HTTP transports."""

from __future__ import annotations

from typing import cast

import httpx

from anis_partners._internal.clock import Clock
from anis_partners._internal.key_document_cache import AsyncKeyDocumentCache
from anis_partners._internal.uuid import canonical
from anis_partners.operations.groups import (
    AsyncCatalogueOperations,
    AsyncDiagnosticsOperations,
    AsyncOrderOperations,
    AsyncOwnedCardOperations,
    AsyncProfileOperations,
    AsyncWalletOperations,
    SyncCatalogueOperations,
    SyncDiagnosticsOperations,
    SyncOrderOperations,
    SyncOwnedCardOperations,
    SyncProfileOperations,
    SyncWalletOperations,
)
from anis_partners.operations.transport import AsyncTransport, RequestCore, SyncTransport
from anis_partners.options import ClientOptions
from anis_partners.signing.errors import RequestSigningError
from anis_partners.signing.nonce import NonceFactory
from anis_partners.signing.p256_signer import AsyncRequestSigner, RequestSigner
from anis_partners.verification.async_http_signing_key_source import AsyncHttpSigningKeySource
from anis_partners.verification.http_signing_key_source import HttpSigningKeySource, KeyDocumentCache
from anis_partners.verification.partner_response_verifier import AsyncPartnerResponseVerifier, PartnerResponseVerifier


class AnisPartnersClient:
    """Call the Partner API with signed requests and verified responses so untrusted bytes never reach models."""

    def __init__(
        self,
        options: ClientOptions,
        signer: RequestSigner,
        *,
        http_client: httpx.Client | None = None,
        key_cache: KeyDocumentCache | None = None,
        clock: Clock | None = None,
        nonce_factory: NonceFactory | None = None,
        name: str = "default",
    ) -> None:
        """Build operation groups over one transport while leaving injected client ownership with the host."""
        self.options = options
        self._owns_http = http_client is None
        _validate_signer(signer)
        self._http = http_client or httpx.Client(timeout=options.timeout_seconds)
        source = HttpSigningKeySource(
            self._http,
            options.authority,
            options.signing_key_cache_seconds,
            key_cache,
            timeout_seconds=options.timeout_seconds,
        )
        self._core = RequestCore(options, signer, clock, nonce_factory, name)
        transport = SyncTransport(self._core, self._http, PartnerResponseVerifier(source, clock))
        self.profile = SyncProfileOperations(transport)
        self.wallets = SyncWalletOperations(transport)
        self.catalogue = SyncCatalogueOperations(transport)
        self.orders = SyncOrderOperations(transport)
        self.owned_cards = SyncOwnedCardOperations(transport)
        self.diagnostics = SyncDiagnosticsOperations(transport)

    def close(self) -> None:
        """Close only a client created here so shared host connections remain usable."""
        self._core.closed = True
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> AnisPartnersClient:
        """Return this client for deterministic cleanup in a with block."""
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Release owned connections without closing an injected transport."""
        self.close()


class AsyncAnisPartnersClient:
    """Call the Partner API asynchronously with the same signing and verification decisions as the sync client."""

    def __init__(
        self,
        options: ClientOptions,
        signer: RequestSigner | AsyncRequestSigner,
        *,
        http_client: httpx.AsyncClient | None = None,
        key_cache: KeyDocumentCache | AsyncKeyDocumentCache | None = None,
        clock: Clock | None = None,
        nonce_factory: NonceFactory | None = None,
        name: str = "default",
    ) -> None:
        """Build async operation groups while retaining host ownership of any injected client."""
        self.options = options
        self._owns_http = http_client is None
        _validate_signer(signer)
        self._http = http_client or httpx.AsyncClient(timeout=options.timeout_seconds)
        source = AsyncHttpSigningKeySource(
            self._http,
            options.authority,
            options.signing_key_cache_seconds,
            key_cache,
            timeout_seconds=options.timeout_seconds,
        )
        self._core = RequestCore(options, signer, clock, nonce_factory, name)
        transport = AsyncTransport(self._core, self._http, AsyncPartnerResponseVerifier(source, clock))
        self.profile = AsyncProfileOperations(transport)
        self.wallets = AsyncWalletOperations(transport)
        self.catalogue = AsyncCatalogueOperations(transport)
        self.orders = AsyncOrderOperations(transport)
        self.owned_cards = AsyncOwnedCardOperations(transport)
        self.diagnostics = AsyncDiagnosticsOperations(transport)

    async def aclose(self) -> None:
        """Close only a client created here so the host can continue using injected connections."""
        self._core.closed = True
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncAnisPartnersClient:
        """Return this client for deterministic cleanup in an async with block."""
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Release owned connections without closing an injected transport."""
        await self.aclose()


def _validate_signer(signer: object) -> None:
    """Fail client construction before a purchase if key identity or signer shape is unusable."""
    try:
        typed = cast(RequestSigner | AsyncRequestSigner, signer)
        if not callable(typed.sign):
            raise TypeError("sign must be callable")
        canonical(typed.key_id)
    except Exception as exc:
        raise RequestSigningError("The request signer is invalid; no request was sent.") from exc
