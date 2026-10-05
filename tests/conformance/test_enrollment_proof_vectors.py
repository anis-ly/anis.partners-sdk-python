"""Enrollment proof message and P1363 output conformance against released vectors."""

import base64
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from anis_partners._internal.base64url import decode
from anis_partners.enrollment.enrollment_proof import EnrollmentProof
from anis_partners.signing.ecdsa_signature_format import der_to_p1363, p1363_to_der
from anis_partners.verification.partner_jwk import PartnerJwk
from tests.support.vectors import read_vector, vector_files


class ProofSigner:
    """Adapts a cryptography key to the proof signer seam."""

    def __init__(self, key: ec.EllipticCurvePrivateKey) -> None:
        self._key = key

    def sign(self, data: bytes) -> bytes:
        """Return P1363 bytes over the proof message."""
        return der_to_p1363(self._key.sign(data, ec.ECDSA(hashes.SHA256())))


def test_enrollment_vector_file_count_is_two() -> None:
    """Fail if the enrollment proof corpus is incomplete."""
    assert len(vector_files("enrollment", "EP")) == 2


@pytest.mark.parametrize("path", vector_files("enrollment", "EP"), ids=lambda path: Path(path).stem)
def test_enrollment_vector_builds_and_signs_exact_proof_message(path: Path) -> None:
    """Check one enrollment message and its P1363 proof signature."""
    vector = read_vector(path)
    submitted = vector["keySubmissionResult"]
    message = EnrollmentProof.proof_message(
        submitted["keyId"],
        submitted["challengeGeneration"],
        submitted["challenge"],
        submitted["thumbprint"],
    )
    assert base64.b64encode(message).decode() == vector["expected"]["proofMessageBase64"]
    private_key = serialization.load_der_private_key(
        base64.b64decode(vector["key"]["privateKeyPkcs8Base64"]), password=None
    )
    assert isinstance(private_key, ec.EllipticCurvePrivateKey)
    signature = decode(EnrollmentProof.proof_signature(message, ProofSigner(private_key)))
    assert signature is not None
    assert len(signature) == 64
    public_key = PartnerJwk(**vector["key"]["publicJwk"]).public_key()
    public_key.verify(p1363_to_der(signature), message, ec.ECDSA(hashes.SHA256()))
