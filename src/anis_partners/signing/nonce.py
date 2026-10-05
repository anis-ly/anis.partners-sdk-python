"""Cryptographically random, single-attempt mutation nonces."""

import secrets
from typing import Protocol

from anis_partners._internal.base64url import encode


class NonceFactory(Protocol):
    """Let hosts supply unpredictable mutation nonces so captured requests cannot be replayed."""

    def create(self) -> str:
        """Return a new nonce for each mutation attempt to make replay detection effective."""


class RandomNonceFactory:
    """Provide unpredictable 128-bit mutation nonces so an observer cannot guess a valid retry token."""

    def create(self) -> str:
        """Use the system CSPRNG because predictable nonces undermine replay protection."""
        return encode(secrets.token_bytes(16))
