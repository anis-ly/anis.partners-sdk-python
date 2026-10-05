"""Request wire-byte conformance against the released .NET SDK vectors."""

import base64
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from anis_partners.signing.content_digest import ContentDigest
from anis_partners.signing.ecdsa_signature_format import p1363_to_der
from anis_partners.signing.partner_request_signer import PartnerRequestSigner
from anis_partners.signing.signature_inputs import SignatureInputs
from anis_partners.signing.signature_profile import SignatureProfile
from anis_partners.verification.partner_jwk import PartnerJwk
from tests.support.vectors import read_vector, vector_files


class VectorSigner:
    """Vector signer adapter exposing the released PKCS#8 key."""

    def __init__(self, key: ec.EllipticCurvePrivateKey, key_id: str) -> None:
        self._key = key
        self.key_id = key_id

    def sign(self, data: bytes) -> bytes:
        """Sign the base and convert cryptography DER output into wire P1363."""
        from anis_partners.signing.ecdsa_signature_format import der_to_p1363

        return der_to_p1363(self._key.sign(data, ec.ECDSA(hashes.SHA256())))


def test_request_vector_file_count_is_nine() -> None:
    """Fail if the request corpus is incomplete."""
    assert len(vector_files("request", "RQ")) == 9


@pytest.mark.parametrize(
    "path",
    vector_files("request", "RQ"),
    ids=lambda path: Path(path).stem,
)
def test_request_vector_reproduces_base_and_signature(path: Path) -> None:
    """Rebuild one request vector's bytes and verify the generated P1363 signature."""
    vector = read_vector(path)
    request = vector["request"]
    key_data = vector["key"]
    private_key = serialization.load_der_private_key(base64.b64decode(key_data["privateKeyPkcs8Base64"]), password=None)
    assert isinstance(private_key, ec.EllipticCurvePrivateKey)
    body_data = request["bodyBase64"]
    body = base64.b64decode(body_data) if body_data is not None else None
    inputs = SignatureInputs(
        method=request["method"],
        authority=request["authorityAsGiven"],
        path=request["path"],
        canonical_query=request["canonicalQuery"],
        anis_date=request["anisDate"],
        content_digest=ContentDigest.of(body) if body is not None else None,
        nonce=request["nonce"],
        idempotency_key=request["idempotencyKey"],
    )
    signed = PartnerRequestSigner(VectorSigner(private_key, key_data["keyId"])).sign(
        SignatureProfile(vector["profile"]),
        inputs,
        vector["signature"]["created"],
        vector["signature"]["expires"],
    )
    expected = vector["expected"]
    assert signed.signature_base.decode("utf-8") == expected["signatureBaseUtf8"]
    assert signed.signature_input == expected["signatureInput"]
    assert signed.content_digest == expected["contentDigest"]
    signature = base64.b64decode(signed.signature.split(":")[1])
    assert len(signature) == 64
    public_key = PartnerJwk(**key_data["publicJwk"]).public_key()
    public_key.verify(p1363_to_der(signature), signed.signature_base, ec.ECDSA(hashes.SHA256()))
