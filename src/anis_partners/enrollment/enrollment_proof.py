"""Build proof bytes that distinguish credential enrollment from every other use of the signing key."""

import hashlib

from anis_partners._internal.base64url import encode
from anis_partners._internal.uuid import canonical
from anis_partners.signing.p256_signer import P256Signer

#: Separates key-possession proofs from signatures for any other purpose.
DOMAIN_SEPARATOR = "anis.partners.v2.credential-proof"


class EnrollmentProof:
    """Bind proof to the key, challenge generation, and domain so unrelated signatures cannot prove enrollment."""

    @staticmethod
    def proof_message(
        key_id: str,
        challenge_generation: int,
        challenge: str,
        thumbprint: str,
    ) -> bytes:
        """Hash the stored challenge and bind shared values; Anis stores only its hash, not the challenge itself."""
        if not challenge:
            raise ValueError("The key submission result carries no challenge.")
        if not thumbprint:
            raise ValueError("The key submission result carries no thumbprint.")
        if challenge_generation < 0:
            raise ValueError("Challenge generation must be a non-negative integer.")
        challenge_hash = hashlib.sha256(challenge.encode("utf-8")).hexdigest()
        return "\n".join(
            (DOMAIN_SEPARATOR, canonical(key_id), str(challenge_generation), challenge_hash, thumbprint)
        ).encode("utf-8")

    @staticmethod
    def proof_signature(message: bytes, signer: P256Signer) -> str:
        """Require 64-byte P1363 because Anis rejects DER or any other proof signature representation."""
        signature = signer.sign(message)
        if len(signature) != 64:
            raise ValueError("An enrollment proof signature must be exactly 64-byte P1363.")
        return encode(signature)
