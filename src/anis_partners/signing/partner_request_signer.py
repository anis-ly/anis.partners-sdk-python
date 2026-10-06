"""Pure request signing over already-canonicalized request facts."""

from __future__ import annotations

import asyncio
import base64
import inspect
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import cast

from anis_partners._internal.uuid import canonical
from anis_partners.signing.errors import RequestSigningError
from anis_partners.signing.p256_signer import AsyncRequestSigner, RequestSigner
from anis_partners.signing.partner_request_signature_base import PartnerRequestSignatureBase
from anis_partners.signing.signature_inputs import SignatureInputs
from anis_partners.signing.signature_profile import SignatureProfile
from anis_partners.signing.signed_request_headers import SignedRequestHeaders


@dataclass(frozen=True, slots=True)
class PartnerRequestSigner:
    """Sign only supplied request facts so retries and conformance checks never hide new time or randomness."""

    signer: RequestSigner | AsyncRequestSigner

    @staticmethod
    def _material(
        signer: RequestSigner | AsyncRequestSigner,
        profile: SignatureProfile,
        inputs: SignatureInputs,
        created: int,
        expires: int,
    ) -> tuple[str, bytes]:
        """Build the bounded key label and signature base before asking the partner's signer to act."""
        if (profile is SignatureProfile.SAFE_READ) != (inputs.nonce is None):
            raise ValueError("Safe reads have no nonce; mutation profiles require one.")
        try:
            key_id = canonical(signer.key_id)
        except Exception as exc:
            raise RequestSigningError("The request could not be signed and was not sent.") from exc
        parameters = PartnerRequestSignatureBase.parameters(profile.components, created, expires, key_id, inputs.nonce)
        return parameters, PartnerRequestSignatureBase.build(profile.components, inputs, parameters)

    def sign(
        self, profile: SignatureProfile, inputs: SignatureInputs, created: int, expires: int
    ) -> SignedRequestHeaders:
        """Return matching headers or a safe not-sent error while preserving the original signer failure as cause."""
        parameters, base = self._material(self.signer, profile, inputs, created, expires)
        try:
            signature = self.signer.sign(base)
            if inspect.isawaitable(signature):
                raise TypeError("An asynchronous signer must be used through the asynchronous client.")
            return self._headers(inputs, parameters, base, signature)
        except RequestSigningError:
            raise
        except Exception as exc:
            raise RequestSigningError("The request could not be signed and was not sent.") from exc

    async def sign_async(
        self, profile: SignatureProfile, inputs: SignatureInputs, created: int, expires: int
    ) -> SignedRequestHeaders:
        """Await native async signers and run synchronous vault calls off-loop without changing wire rules."""
        parameters, base = await asyncio.to_thread(self._material, self.signer, profile, inputs, created, expires)
        try:
            method = self.signer.sign
            if inspect.iscoroutinefunction(method):
                result: object = method(base)
            else:

                def invoke() -> object:
                    return method(base)

                result = await asyncio.to_thread(invoke)
            if inspect.isawaitable(result):
                result = await cast(Awaitable[object], result)
            return self._headers(inputs, parameters, base, result)
        except RequestSigningError:
            raise
        except Exception as exc:
            raise RequestSigningError("The request could not be signed and was not sent.") from exc

    @staticmethod
    def _headers(inputs: SignatureInputs, parameters: str, base: bytes, signature: object) -> SignedRequestHeaders:
        """Require 64-byte P-256 output before placing a signature on the wire."""
        if not isinstance(signature, (bytes, bytearray, memoryview)) or len(signature) != 64:
            length = len(signature) if isinstance(signature, (bytes, bytearray, memoryview)) else -1
            hint = " A 70\u201372 byte result is almost certainly DER." if 70 <= length <= 72 else ""
            raise RequestSigningError(f"The signer must return 64-byte P-256 P1363 data.{hint}")
        encoded = base64.b64encode(bytes(signature)).decode("ascii")
        return SignedRequestHeaders(
            signature_input=f"sig1={parameters}",
            signature=f"sig1=:{encoded}:",
            anis_date=inputs.anis_date,
            content_digest=inputs.content_digest,
            nonce=inputs.nonce,
            idempotency_key=str(inputs.idempotency_key) if inputs.idempotency_key is not None else None,
            signature_base=base,
        )
