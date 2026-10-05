"""PEM key loading and wire-compatible P-256 signing."""

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from anis_partners._internal.base64url import decode
from anis_partners.signing.ecdsa_signature_format import p1363_to_der
from anis_partners.signing.pem_p256_signer import PemP256Signer


def test_pem_signer_produces_64_verifiable_bytes() -> None:
    """A PEM-loaded P-256 key signs in the form partners and gateway exchange."""
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    signer = PemP256Signer.from_pem(pem)
    signature = signer.sign(b"signed partner bytes")
    assert len(signature) == 64
    key.public_key().verify(p1363_to_der(signature), b"signed partner bytes", ec.ECDSA(hashes.SHA256()))


def test_pem_signer_refuses_p384_during_load() -> None:
    """An unsupported curve is reported before any API request can be attempted."""
    key = ec.generate_private_key(ec.SECP384R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with pytest.raises(ValueError, match="P-256"):
        PemP256Signer.from_pem(pem)


def test_public_jwk_coordinates_are_exactly_32_bytes() -> None:
    """The public key exports the two fixed-width P-256 coordinates."""
    signer = PemP256Signer(ec.generate_private_key(ec.SECP256R1()))
    jwk = signer.public_jwk()
    x = decode(jwk.x)
    y = decode(jwk.y)
    assert x is not None
    assert len(x) == 32
    assert y is not None
    assert len(y) == 32
