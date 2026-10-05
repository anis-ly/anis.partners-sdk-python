"""Signer protocols keep private key custody under the partner's control."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class P256Signer(Protocol):
    """Keep private key custody in partner vaults or HSMs behind the exact bytes Anis accepts."""

    def sign(self, data: bytes) -> bytes:
        """Return 64-byte P1363; returning DER makes the gateway refuse the request."""


@runtime_checkable
class RequestSigner(P256Signer, Protocol):
    """Bind external key custody to the enrolled id so Anis can select the matching public key."""

    @property
    def key_id(self) -> str:
        """Return the canonical id because the signed `keyid` must match the enrolled credential exactly."""
