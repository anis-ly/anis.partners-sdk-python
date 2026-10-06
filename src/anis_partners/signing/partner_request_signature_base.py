"""Builds request signature parameters and exact RFC 9421 base bytes."""

from collections.abc import Sequence

from anis_partners.signing.signature_inputs import SignatureInputs


class PartnerRequestSignatureBase:
    """Render fixed signature bytes so caller-supplied time and nonce stay reproducible and reviewable."""

    LABEL = "sig1"
    ALGORITHM = "ecdsa-p256-sha256"
    MAX_LIFETIME_SECONDS = 300

    @classmethod
    def parameters(
        cls, components: Sequence[str], created: int, expires: int, key_id: str, nonce: str | None = None
    ) -> str:
        """Enforce Anis's 300-second request lifetime; longer signatures are refused by the gateway."""
        if expires - created > cls.MAX_LIFETIME_SECONDS:
            raise ValueError("A Partner signature may live at most 300 seconds.")
        if nonce is not None and (
            not nonce or any(char in '"\\' or ord(char) < 32 or 0x7F <= ord(char) <= 0x9F for char in nonce)
        ):
            raise ValueError("A nonce must be a non-empty structured-field string without quotes or controls.")
        quoted = " ".join(f'"{component}"' for component in components)
        result = f'({quoted});created={created};expires={expires};keyid="{key_id}";alg="{cls.ALGORITHM}"'
        return result if nonce is None else f'{result};nonce="{nonce}"'

    @classmethod
    def build(cls, components: Sequence[str], inputs: SignatureInputs, parameters: str) -> bytes:
        """Match RFC 9421 byte-for-byte; even a trailing newline makes Anis verify different bytes."""
        lines = [f'"{name}": {inputs.value_of(name)}' for name in components]
        lines.append(f'"@signature-params": {parameters}')
        return "\n".join(lines).encode("utf-8")
