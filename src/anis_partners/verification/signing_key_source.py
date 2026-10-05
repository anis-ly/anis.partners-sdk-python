"""Separate key rotation I/O from shared verification rules so sync and async callers refuse identically."""

from typing import Protocol

from anis_partners.verification.partner_jwk import SigningKeySet


class SigningKeySource(Protocol):
    """Keep rotation retrieval separate so the verifier can refresh an unknown id exactly once."""

    def get(self) -> SigningKeySet:
        """Reuse current keys or fetch them so every response is checked against a published version."""

    def refresh(self) -> SigningKeySet:
        """Refresh once after an unknown id so a legitimate rotation recovers without retry loops."""


class AsyncSigningKeySource(Protocol):
    """Preserve the same bounded rotation behavior for applications using async HTTP."""

    async def get(self) -> SigningKeySet:
        """Reuse current keys or fetch them so every response is checked against a published version."""

    async def refresh(self) -> SigningKeySet:
        """Refresh once after an unknown id so a legitimate rotation recovers without retry loops."""
