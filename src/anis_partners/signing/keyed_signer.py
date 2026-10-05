"""Adds a credential identifier to a signer without transferring key custody."""

from dataclasses import dataclass

from anis_partners._internal.uuid import canonical
from anis_partners.signing.p256_signer import P256Signer


@dataclass(frozen=True, slots=True)
class KeyedSigner:
    """Pair host-owned key custody with its enrolled identity so signatures use the intended credential."""

    #: Byte-only signing seam lets the host keep using its chosen key custody.
    signer: P256Signer
    #: Enrolled identifier binds this request to the partner's credential.
    key_id: str

    def __post_init__(self) -> None:
        """Canonicalize once so differently cased UUIDs cannot sign a different key identifier."""
        object.__setattr__(self, "key_id", canonical(self.key_id))

    def sign(self, data: bytes) -> bytes:
        """Delegate custody to the selected signer while retaining the common P-256 wire contract."""
        return self.signer.sign(data)
