"""Test unsigned enrollment requests and verified, thumbprint-bound answers."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from anis_partners import EnrollmentRefusedError
from anis_partners.enrollment.client import AnisEnrollmentClient, EnrollmentKeyMismatchError
from anis_partners.enrollment.enrollment_proof import EnrollmentProof
from anis_partners.enrollment.key_thumbprint import compute
from anis_partners.models import EnrollmentKeyRequest, EnrollmentKeyResult, EnrollmentProofRequest, EnrollmentStatus
from anis_partners.signing.ecdsa_signature_format import der_to_p1363
from anis_partners.signing.p256_signer import P256Signer
from anis_partners.verification.partner_jwk import PartnerJwk
from tests.support.sdk_wire import SignedMockWire, WireAnswer

INVITATION = UUID("3f2a9c14-8d6e-4b21-9f07-5c8ab2d61e43")
TOKEN = "-".join(("enrollment", "token", "test", "only"))


class _ProofSigner:
    """Sign the enrollment proof with a throwaway P-256 key in the public signer format."""

    def __init__(self) -> None:
        self._key = ec.generate_private_key(ec.SECP256R1())

    def sign(self, data: bytes) -> bytes:
        return der_to_p1363(self._key.sign(data, ec.ECDSA(hashes.SHA256())))


def _jwk() -> PartnerJwk:
    """Create a fresh test public key in the JWK shape sent to enrollment."""
    from anis_partners._internal.base64url import encode

    point = ec.generate_private_key(ec.SECP256R1()).public_key().public_numbers()
    return PartnerJwk("EC", "P-256", encode(point.x.to_bytes(32, "big")), encode(point.y.to_bytes(32, "big")))


def test_submit_key_sends_only_public_jwk_with_enrollment_authorization() -> None:
    """Keep the token out of signature headers and private key members out of the submission body."""
    public_jwk = _jwk()
    thumbprint = compute(public_jwk)
    answer = {
        "keyId": "c31ce82f-2a51-4f86-a1cc-3f5dc4b8f021",
        "thumbprint": thumbprint,
        "challenge": "challenge-value",
        "challengeGeneration": 1,
    }
    wire = SignedMockWire(lambda request: WireAnswer(body=json.dumps(answer).encode()))
    http = cast(httpx.Client, wire.client())
    client = AnisEnrollmentClient("https://partners.test", INVITATION, TOKEN, http_client=http)
    try:
        result = client.submit_key(
            EnrollmentKeyRequest(public_jwk, datetime.now(UTC), datetime.now(UTC) + timedelta(days=365))
        )
        request = next(item for item in wire.requests if item.url.path.endswith("/keys"))
        body = request.content.decode()
        assert request.headers["Authorization"] == f"Enrollment {TOKEN}"
        assert "Signature" not in request.headers
        assert "Signature-Input" not in request.headers
        assert '"d"' not in body
        assert '"cidrs"' not in body
        assert result.thumbprint == thumbprint
        assert result.safety_code is not None
    finally:
        client.close()
        http.close()


def test_submit_key_stops_on_a_mismatched_server_thumbprint() -> None:
    """Do not expose a challenge that belongs to a different credential than the one submitted."""
    public_jwk = _jwk()
    wire = SignedMockWire(
        lambda request: WireAnswer(
            body=b'{"keyId":"c31ce82f-2a51-4f86-a1cc-3f5dc4b8f021","thumbprint":"wrong","challenge":"secret-challenge","challengeGeneration":1}'
        )
    )
    http = cast(httpx.Client, wire.client())
    client = AnisEnrollmentClient("https://partners.test", INVITATION, TOKEN, http_client=http)
    try:
        with pytest.raises(EnrollmentKeyMismatchError) as caught:
            client.submit_key(
                EnrollmentKeyRequest(public_jwk, datetime.now(UTC), datetime.now(UTC) + timedelta(days=365))
            )
        assert caught.value.local_thumbprint == compute(public_jwk)
        assert caught.value.server_thumbprint == "wrong"
        assert "secret-challenge" not in str(caught.value)
        assert len([item for item in wire.requests if item.url.path.endswith("/keys")]) == 1
    finally:
        client.close()
        http.close()


@pytest.mark.anyio
async def test_async_enrollment_uses_the_same_verified_unsigned_request_flow() -> None:
    """Keep async enrollment unsigned on the request side while retaining response verification."""
    from anis_partners.enrollment.client import AsyncAnisEnrollmentClient

    wire = SignedMockWire(
        lambda request: WireAnswer(
            body=b'{"invitationId":"3f2a9c14-8d6e-4b21-9f07-5c8ab2d61e43","state":"pendingPublicKey"}'
        )
    )
    http = cast(httpx.AsyncClient, wire.client(async_client=True))
    async with AsyncAnisEnrollmentClient("https://partners.test", INVITATION, TOKEN, http_client=http) as client:
        state = await client.get()
        request = next(item for item in wire.requests if item.url.path.endswith(str(INVITATION)))
        assert state.state == "pendingPublicKey"
        assert request.headers["Authorization"] == f"Enrollment {TOKEN}"
        assert "Signature" not in request.headers
        assert wire.key_document_requests == 1
    await http.aclose()


def test_submit_then_prove_verifies_both_unsigned_enrollment_answers() -> None:
    """Walk key submission and challenge proof while each answer remains signed and verified."""
    public_jwk = _jwk()
    thumbprint = compute(public_jwk)
    answers = [
        WireAnswer(
            body=json.dumps(
                {
                    "keyId": str(INVITATION),
                    "thumbprint": thumbprint,
                    "challenge": "challenge-for-proof",
                    "challengeGeneration": 3,
                }
            ).encode()
        ),
        WireAnswer(
            body=b'{"keyId":"3f2a9c14-8d6e-4b21-9f07-5c8ab2d61e43","challengeGeneration":3,"proofState":"accepted","approvalState":"pendingApproval","state":"pendingApproval"}'
        ),
    ]
    wire = SignedMockWire(lambda request: answers.pop(0))
    http = cast(httpx.Client, wire.client())
    client = AnisEnrollmentClient("https://partners.test", INVITATION, TOKEN, http_client=http)
    request = EnrollmentKeyRequest(public_jwk, datetime.now(UTC), datetime.now(UTC) + timedelta(days=365))
    try:
        submitted = client.submit_key(request)
        status = client.prove(submitted, _ProofSigner())
        assert status.state == "pendingApproval"
        assert status.proof_state == "accepted"
        key_request, proof_request = [item for item in wire.requests if "/v1/enrollments/" in item.url.path]
        assert key_request.url.path.endswith("/keys")
        assert proof_request.url.path.endswith("/proof")
        assert all(item.headers["Authorization"] == f"Enrollment {TOKEN}" for item in (key_request, proof_request))
        assert all("Signature" not in item.headers for item in (key_request, proof_request))
        sent_proof = json.loads(proof_request.content)
        assert sent_proof["challengeGeneration"] == 3
        assert len(sent_proof["signature"]) == 86
        assert "=" not in sent_proof["signature"]
        assert '"d"' not in key_request.content.decode()
    finally:
        client.close()
        http.close()


def test_enrollment_proof_refuses_non_p1363_signatures_before_sending() -> None:
    """Reject DER-length signatures locally because the enrollment API accepts fixed-width P1363 only."""

    class DerSigner:
        def sign(self, data: bytes) -> bytes:
            return b"x" * 71

    with pytest.raises(ValueError, match="exactly 64-byte P1363"):
        EnrollmentProof.proof_signature(b"proof", cast(P256Signer, DerSigner()))


def test_unprovable_submission_stops_before_an_http_request() -> None:
    """Require challenge fields before producing a proof so no unrelated signature can be submitted."""
    wire = SignedMockWire()
    http = cast(httpx.Client, wire.client())
    client = AnisEnrollmentClient("https://partners.test", INVITATION, TOKEN, http_client=http)
    try:
        with pytest.raises(ValueError, match="missing proof fields"):
            client.prove(EnrollmentKeyResult(key_id=INVITATION), _ProofSigner())
        assert wire.requests == []
    finally:
        client.close()
        http.close()


def test_enrollment_refusal_is_a_typed_enrollment_exception() -> None:
    """Preserve the verified challenge refusal as an enrollment-specific API error."""
    wire = SignedMockWire(
        lambda request: WireAnswer(
            409,
            b'{"type":"https://developers.anis.ly/errors/challenge-expired","title":"expired","status":409,"code":"challenge_expired"}',
        )
    )
    http = cast(httpx.Client, wire.client())
    client = AnisEnrollmentClient("https://partners.test", INVITATION, TOKEN, http_client=http)
    try:
        with pytest.raises(EnrollmentRefusedError) as failure:
            client.submit_proof(EnrollmentProofRequest(INVITATION, 1, "A" * 86))
        assert failure.value.code.value == "challenge_expired"
    finally:
        client.close()
        http.close()


def test_enrollment_status_preserves_optional_key_expiry() -> None:
    """Carry key expiry when present while allowing statuses that omit it."""
    active = EnrollmentStatus.from_json(
        '{"keyId":"3f2a9c14-8d6e-4b21-9f07-5c8ab2d61e43","state":"active","approvalState":"approved","keyExpiresAt":"2027-09-30T12:00:00Z"}'
    )
    without_expiry = EnrollmentStatus.from_json('{"state":"active","approvalState":"approved"}')
    assert active.key_expires_at == datetime(2027, 9, 30, 12, tzinfo=UTC)
    assert without_expiry.key_expires_at is None


def test_enrollment_request_is_measured_without_recording_its_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Measure the shared enrollment transport while keeping its bearer token off telemetry dimensions."""
    import anis_partners.operations.transport as transport

    samples: list[tuple[object, object]] = []

    class Recorder:
        def record(self, value: object, attributes: object = None) -> None:
            samples.append((value, attributes))

    monkeypatch.setattr(transport, "request_duration", Recorder())
    wire = SignedMockWire(
        lambda request: WireAnswer(
            body=b'{"invitationId":"3f2a9c14-8d6e-4b21-9f07-5c8ab2d61e43","state":"pendingPublicKey"}'
        )
    )
    http = cast(httpx.Client, wire.client())
    client = AnisEnrollmentClient("https://partners.test", INVITATION, TOKEN, http_client=http)
    try:
        state = client.get()
        assert state.state == "pendingPublicKey"
        assert samples
        assert "/v1/enrollments/{invitationId}" in repr(samples)
        assert TOKEN not in repr(samples)
        request = next(item for item in wire.requests if item.url.path.endswith(str(INVITATION)))
        assert request.headers["Authorization"] == f"Enrollment {TOKEN}"
        assert "Signature" not in request.headers
    finally:
        client.close()
        http.close()


def test_thumbprint_ignores_private_and_noncanonical_key_members() -> None:
    """Fingerprint only public RFC 7638 members so private material cannot change the server comparison."""
    public_jwk = _jwk()
    with_private_member = PartnerJwk(
        public_jwk.kty, public_jwk.crv, public_jwk.x, public_jwk.y, kid="ignored", d="private-scalar"
    )
    assert compute(public_jwk) == compute(with_private_member)


def test_incomplete_or_other_curve_jwks_cannot_be_fingerprinted() -> None:
    """Refuse incomplete or non-P-256 keys before a partner submits an unverifiable credential."""
    public_jwk = _jwk()
    with pytest.raises(ValueError, match="P-256"):
        compute(PartnerJwk("EC", "P-384", public_jwk.x, public_jwk.y))
    with pytest.raises(ValueError, match="32-byte"):
        compute(PartnerJwk("EC", "P-256", "AA", public_jwk.y))


@pytest.fixture
def anyio_backend() -> str:
    """Keep async transport tests on asyncio to match the supported SDK runtime."""
    return "asyncio"
