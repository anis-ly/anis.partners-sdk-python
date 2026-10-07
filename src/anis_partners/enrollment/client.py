"""Enrollment clients that keep token requests unsigned while verifying every answer."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

import httpx

from anis_partners._internal.clock import Clock
from anis_partners._internal.uuid import parse as parse_uuid
from anis_partners.enrollment.enrollment_proof import EnrollmentProof
from anis_partners.enrollment.key_thumbprint import compute as compute_thumbprint
from anis_partners.enrollment.safety_code import SafetyCode
from anis_partners.errors import AnisPartnersError
from anis_partners.models import (
    EnrollmentKeyRequest,
    EnrollmentKeyResult,
    EnrollmentProofRequest,
    EnrollmentState,
    EnrollmentStatus,
)
from anis_partners.operations.transport import AsyncTransport, RequestCore, RequestSpec, SyncTransport
from anis_partners.options import ClientOptions
from anis_partners.signing.p256_signer import AsyncP256Signer, P256Signer
from anis_partners.verification.async_http_signing_key_source import AsyncHttpSigningKeySource
from anis_partners.verification.http_signing_key_source import HttpSigningKeySource
from anis_partners.verification.partner_jwk import PartnerJwk
from anis_partners.verification.partner_response_verifier import (
    AsyncPartnerResponseVerifier,
    PartnerResponseVerifier,
)
from anis_partners.verification.signing_key_source import AsyncSigningKeySource, SigningKeySource

T = TypeVar("T")


def _validate_enrollment_token(token: str) -> None:
    """Reject token bytes HTTP headers cannot safely carry before passing them to the transport."""
    if not isinstance(token, str) or not token or any(not 0x21 <= ord(character) <= 0x7E for character in token):
        raise ValueError("Enrollment token must contain only visible ASCII characters.")


class EnrollmentKeyMismatchError(AnisPartnersError):
    """Stop if a mismatched thumbprint would otherwise enroll the wrong signing credential."""

    def __init__(self, local_thumbprint: str, server_thumbprint: str | None) -> None:
        """Retain fingerprints for diagnosis without exposing the challenge or enrollment token."""
        super().__init__(
            "The key Anis holds is not the key you submitted. Do not prove possession; "
            "ask Anis staff to restart enrollment."
        )
        self.local_thumbprint = local_thumbprint
        self.server_thumbprint = server_thumbprint

    def __reduce__(self) -> tuple[type[EnrollmentKeyMismatchError], tuple[str, str | None]]:
        """Preserve both fingerprints when the host copies or serializes this enrollment refusal."""
        return (type(self), (self.local_thumbprint, self.server_thumbprint))


def _enrollment_spec(
    core: RequestCore, method: str, template: str, path: str, body: object | None, token: str
) -> RequestSpec:
    """Use the published token-authorized route; Anis signs every enrollment answer, so verification is mandatory."""
    from anis_partners.operations.routes import PARTNER_ROUTES

    route = next((item for item in PARTNER_ROUTES if item.method == method and item.template == template), None)
    if route is None or route.profile is not None or not route.signs_response:
        raise ValueError("Enrollment requests must use a published unsigned enrollment route with signed answers.")
    return RequestSpec(
        method,
        template,
        path,
        None,
        core.body_bytes(body),
        authorization=f"Enrollment {token}",
        signs_response=route.signs_response,
    )


class AnisEnrollmentClient:
    """Bootstrap a credential before request signing exists, while refusing any unverifiable enrollment answer."""

    def __init__(
        self,
        authority: str,
        invitation_id: UUID | str,
        enrollment_token: str,
        *,
        http_client: httpx.Client | None = None,
        keys: SigningKeySource | None = None,
        clock: Clock | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        """Use an unsigned request path because no partner key exists yet; injected transport stays host-owned."""
        _validate_enrollment_token(enrollment_token)
        self.invitation_id = parse_uuid(invitation_id, "invitation_id")
        self._token = enrollment_token
        self._owns_http = http_client is None
        options = ClientOptions(authority, timeout_seconds=timeout_seconds)
        self._http = http_client or httpx.Client(timeout=options.timeout_seconds)
        source = keys or HttpSigningKeySource(
            self._http, options.authority, options.signing_key_cache_seconds, timeout_seconds=options.timeout_seconds
        )
        self._core = RequestCore(options, None, clock)
        self._transport = SyncTransport(self._core, self._http, PartnerResponseVerifier(source, clock))

    def __repr__(self) -> str:
        """Expose the invitation identity while ensuring native inspection cannot reveal the one-time token."""
        return f"AnisEnrollmentClient(invitation_id={self.invitation_id!r}, enrollment_token=<redacted>)"

    def close(self) -> None:
        """Close only the internally created HTTP client."""
        self._core.closed = True
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> AnisEnrollmentClient:
        """Return this enrollment client for scoped cleanup."""
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Release owned transport resources after the human approval flow."""
        self.close()

    def get(self) -> EnrollmentState:
        """Read invitation state before creating a key, so expired invitations do not start a partial flow."""
        return self._send(
            "GET",
            "/v1/enrollments/{invitationId}",
            f"/v1/enrollments/{self.invitation_id}",
            None,
            EnrollmentState.from_json,
        )

    def get_status(self) -> EnrollmentStatus:
        """Read approval and key expiry separately so pending proof is never mistaken for activation."""
        route = "/v1/enrollments/{invitationId}/status"
        return self._send(
            "GET", route, f"/v1/enrollments/{self.invitation_id}/status", None, EnrollmentStatus.from_json
        )

    def submit_key(self, request: EnrollmentKeyRequest) -> EnrollmentKeyResult:
        """Submit only public key members and compare Anis's verified fingerprint before returning a challenge."""
        local = compute_thumbprint(request.public_jwk)
        public = PartnerJwk(
            kty=request.public_jwk.kty, crv=request.public_jwk.crv, x=request.public_jwk.x, y=request.public_jwk.y
        )
        body = {"publicJwk": public.to_json(), "notBefore": request.not_before, "expiresAt": request.expires_at}
        route = "/v1/enrollments/{invitationId}/keys"
        result = self._send(
            "POST", route, f"/v1/enrollments/{self.invitation_id}/keys", body, EnrollmentKeyResult.from_json
        )
        if not result.thumbprint or not hmac.compare_digest(local.encode(), result.thumbprint.encode()):
            raise EnrollmentKeyMismatchError(local, result.thumbprint)
        return EnrollmentKeyResult(
            result.key_id,
            result.thumbprint,
            SafetyCode.from_thumbprint(local),
            result.challenge,
            result.challenge_generation,
        )

    def submit_proof(self, request: EnrollmentProofRequest) -> EnrollmentStatus:
        """Submit a possession proof under the server's current challenge generation."""
        route = "/v1/enrollments/{invitationId}/proof"
        return self._send(
            "POST", route, f"/v1/enrollments/{self.invitation_id}/proof", request, EnrollmentStatus.from_json
        )

    def prove(self, submitted: EnrollmentKeyResult, signer: P256Signer) -> EnrollmentStatus:
        """Build and send the exact domain-separated proof so the submitted private key is proven without export."""
        if submitted.challenge is None or submitted.thumbprint is None or submitted.challenge_generation is None:
            raise ValueError("The key submission result is missing proof fields.")
        message = EnrollmentProof.proof_message(
            str(submitted.key_id), submitted.challenge_generation, submitted.challenge, submitted.thumbprint
        )
        signature = EnrollmentProof.proof_signature(message, signer)
        return self.submit_proof(EnrollmentProofRequest(submitted.key_id, submitted.challenge_generation, signature))

    def _send(self, method: str, route: str, path: str, body: object | None, reader: Callable[[object], T]) -> T:
        spec = _enrollment_spec(self._core, method, route, path, body, self._token)
        return self._transport.send(spec, reader)[0]


class AsyncAnisEnrollmentClient:
    """Bootstrap credentials asynchronously while keeping token requests unsigned and answers verified."""

    def __init__(
        self,
        authority: str,
        invitation_id: UUID | str,
        enrollment_token: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        keys: AsyncSigningKeySource | None = None,
        clock: Clock | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        """Keep the async host transport and key source so enrollment can run inside an existing event loop."""
        _validate_enrollment_token(enrollment_token)
        self.invitation_id = parse_uuid(invitation_id, "invitation_id")
        self._token = enrollment_token
        self._owns_http = http_client is None
        options = ClientOptions(authority, timeout_seconds=timeout_seconds)
        self._http = http_client or httpx.AsyncClient(timeout=options.timeout_seconds)
        source = keys or AsyncHttpSigningKeySource(
            self._http, options.authority, options.signing_key_cache_seconds, timeout_seconds=options.timeout_seconds
        )
        self._core = RequestCore(options, None, clock)
        self._transport = AsyncTransport(self._core, self._http, AsyncPartnerResponseVerifier(source, clock))

    def __repr__(self) -> str:
        """Expose the invitation identity while ensuring native inspection cannot reveal the one-time token."""
        return f"AsyncAnisEnrollmentClient(invitation_id={self.invitation_id!r}, enrollment_token=<redacted>)"

    async def aclose(self) -> None:
        """Close the internally created HTTP client without taking ownership of injected transports."""
        self._core.closed = True
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncAnisEnrollmentClient:
        """Return the async enrollment client for scoped cleanup."""
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Release owned transport resources after the enrollment flow."""
        await self.aclose()

    async def get(self) -> EnrollmentState:
        """Read invitation state before generating or submitting a key."""
        return await self._send(
            "GET",
            "/v1/enrollments/{invitationId}",
            f"/v1/enrollments/{self.invitation_id}",
            None,
            EnrollmentState.from_json,
        )

    async def get_status(self) -> EnrollmentStatus:
        """Read proof, approval, and expiry state without inferring activation."""
        route = "/v1/enrollments/{invitationId}/status"
        return await self._send(
            "GET", route, f"/v1/enrollments/{self.invitation_id}/status", None, EnrollmentStatus.from_json
        )

    async def submit_key(self, request: EnrollmentKeyRequest) -> EnrollmentKeyResult:
        """Verify the returned thumbprint and derive the phone code locally before exposing the challenge."""
        local = compute_thumbprint(request.public_jwk)
        public = PartnerJwk(
            kty=request.public_jwk.kty, crv=request.public_jwk.crv, x=request.public_jwk.x, y=request.public_jwk.y
        )
        body = {"publicJwk": public.to_json(), "notBefore": request.not_before, "expiresAt": request.expires_at}
        route = "/v1/enrollments/{invitationId}/keys"
        result = await self._send(
            "POST", route, f"/v1/enrollments/{self.invitation_id}/keys", body, EnrollmentKeyResult.from_json
        )
        if not result.thumbprint or not hmac.compare_digest(local.encode(), result.thumbprint.encode()):
            raise EnrollmentKeyMismatchError(local, result.thumbprint)
        return EnrollmentKeyResult(
            result.key_id,
            result.thumbprint,
            SafetyCode.from_thumbprint(local),
            result.challenge,
            result.challenge_generation,
        )

    async def submit_proof(self, request: EnrollmentProofRequest) -> EnrollmentStatus:
        """Submit a proof for the current challenge generation."""
        route = "/v1/enrollments/{invitationId}/proof"
        return await self._send(
            "POST", route, f"/v1/enrollments/{self.invitation_id}/proof", request, EnrollmentStatus.from_json
        )

    async def prove(self, submitted: EnrollmentKeyResult, signer: P256Signer | AsyncP256Signer) -> EnrollmentStatus:
        """Sign and submit the proof message while keeping private key custody with the partner."""
        if submitted.challenge is None or submitted.thumbprint is None or submitted.challenge_generation is None:
            raise ValueError("The key submission result is missing proof fields.")
        message = EnrollmentProof.proof_message(
            str(submitted.key_id), submitted.challenge_generation, submitted.challenge, submitted.thumbprint
        )
        signature = await EnrollmentProof.proof_signature_async(message, signer)
        return await self.submit_proof(
            EnrollmentProofRequest(submitted.key_id, submitted.challenge_generation, signature)
        )

    async def _send(self, method: str, route: str, path: str, body: object | None, reader: Callable[[object], T]) -> T:
        spec = _enrollment_spec(self._core, method, route, path, body, self._token)
        return (await self._transport.send(spec, reader))[0]
