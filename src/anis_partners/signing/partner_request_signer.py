"""Pure request signing over already-canonicalized request facts."""

import base64
from dataclasses import dataclass

from anis_partners._internal.uuid import canonical
from anis_partners.signing.errors import RequestSigningError
from anis_partners.signing.p256_signer import RequestSigner
from anis_partners.signing.partner_request_signature_base import PartnerRequestSignatureBase
from anis_partners.signing.signature_inputs import SignatureInputs
from anis_partners.signing.signature_profile import SignatureProfile
from anis_partners.signing.signed_request_headers import SignedRequestHeaders


@dataclass(frozen=True, slots=True)
class PartnerRequestSigner:
    """Sign only supplied request facts so retries and conformance checks never hide new time or randomness."""

    signer: RequestSigner

    def sign(
        self, profile: SignatureProfile, inputs: SignatureInputs, created: int, expires: int
    ) -> SignedRequestHeaders:
        """Return matching headers and bytes, or fail before transport can send an unsigned request."""
        if (profile is SignatureProfile.SAFE_READ) != (inputs.nonce is None):
            raise ValueError("Safe reads have no nonce; mutation profiles require one.")
        key_id = canonical(self.signer.key_id)
        parameters = PartnerRequestSignatureBase.parameters(profile.components, created, expires, key_id, inputs.nonce)
        base = PartnerRequestSignatureBase.build(profile.components, inputs, parameters)
        try:
            signature = self.signer.sign(base)
        except Exception as exc:
            raise RequestSigningError("The P-256 signer failed while signing the request.") from exc
        if len(signature) != 64:
            size_hint = " A 70\u201372 byte result is almost certainly DER." if 70 <= len(signature) <= 72 else ""
            raise RequestSigningError(
                f"The signer returned {len(signature)} bytes; P-256 P1363 is exactly 64.{size_hint}"
            )
        encoded = base64.b64encode(signature).decode("ascii")
        return SignedRequestHeaders(
            signature_input=f"sig1={parameters}",
            signature=f"sig1=:{encoded}:",
            anis_date=inputs.anis_date,
            content_digest=inputs.content_digest,
            nonce=inputs.nonce,
            idempotency_key=str(inputs.idempotency_key) if inputs.idempotency_key is not None else None,
            signature_base=base,
        )
