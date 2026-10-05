"""PEM-backed P-256 signer for hosts that protect a key file."""

from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from anis_partners._internal.base64url import encode
from anis_partners.signing.ecdsa_signature_format import der_to_p1363
from anis_partners.signing.keyed_signer import KeyedSigner
from anis_partners.verification.partner_jwk import PartnerJwk


@dataclass(frozen=True, slots=True)
class PemP256Signer:
    """Offer file-backed signing for hosts that protect PEM keys; vault and HSM hosts can provide another signer."""

    _private_key: ec.EllipticCurvePrivateKey

    @classmethod
    def from_pem(cls, pem: str | bytes) -> "PemP256Signer":
        """Refuse non-P-256 keys at load time so curve mismatch cannot surface as a later Anis refusal."""
        raw = pem.encode() if isinstance(pem, str) else pem
        key = serialization.load_pem_private_key(raw, password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError("The Anis Partner API accepts NIST P-256 private keys only.")
        return cls(key)

    @classmethod
    def from_pem_file(cls, path: str | Path) -> "PemP256Signer":
        """Load from a host-protected file so the private key never needs to enter request code."""
        return cls.from_pem(Path(path).read_bytes())

    def sign(self, data: bytes) -> bytes:
        """Convert the library's DER result because Anis accepts only 64-byte P1363 signatures."""
        return der_to_p1363(self._private_key.sign(data, ec.ECDSA(hashes.SHA256())))

    def public_jwk(self) -> "PartnerJwk":
        """Export only the public coordinates Anis needs, keeping the private scalar out of enrollment data."""
        numbers = self._private_key.public_key().public_numbers()
        return PartnerJwk(
            kty="EC",
            crv="P-256",
            x=encode(numbers.x.to_bytes(32, "big")),
            y=encode(numbers.y.to_bytes(32, "big")),
        )

    def for_key(self, key_id: str) -> KeyedSigner:
        """Bind this private key to the id Anis assigned so requests name the right credential."""
        return KeyedSigner(self, key_id)
