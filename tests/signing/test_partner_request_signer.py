"""Request signer refusal rules and secret-safe errors."""

import pytest

from anis_partners.signing.errors import RequestSigningError
from anis_partners.signing.partner_request_signer import PartnerRequestSigner
from anis_partners.signing.signature_inputs import SignatureInputs
from anis_partners.signing.signature_profile import SignatureProfile

KEY_ID = "3f2a9c14-8d6e-4b21-9f07-5c8ab2d61e43"


class StubSigner:
    """Injects a result or failure from a partner-owned signer."""

    key_id = KEY_ID

    def __init__(self, result: bytes | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error

    def sign(self, data: bytes) -> bytes:
        """Return the selected fake signature result."""
        if self.error is not None:
            raise self.error
        return self.result or b"x" * 64


def inputs(nonce: str | None = None) -> SignatureInputs:
    """Return the minimal request facts for one signing attempt."""
    return SignatureInputs("get", "PARTNERS.ANIS.LY", "/v1/profile", "", "2026-09-19T08:00:00Z", nonce=nonce)


def test_71_byte_der_like_result_fails_without_secret_material_in_message() -> None:
    """A DER-sized result is wrapped before any request could be sent."""
    with pytest.raises(RequestSigningError) as caught:
        PartnerRequestSigner(StubSigner(b"s" * 71)).sign(SignatureProfile.SAFE_READ, inputs(), 10, 70)
    assert "70\u201372" in str(caught.value)
    assert "signature-base" not in str(caught.value).lower()
    assert "s" * 30 not in str(caught.value)


def test_signer_exception_is_preserved_as_cause() -> None:
    """The host can inspect its original vault failure while the SDK message stays safe."""
    original = RuntimeError("vault temporarily unavailable")
    with pytest.raises(RequestSigningError) as caught:
        PartnerRequestSigner(StubSigner(error=original)).sign(SignatureProfile.SAFE_READ, inputs(), 10, 70)
    assert caught.value.__cause__ is original
    assert "vault temporarily unavailable" not in str(caught.value)


def test_nonce_presence_must_match_the_selected_profile() -> None:
    """Reads omit nonce and mutations require it before signing begins."""
    signer = PartnerRequestSigner(StubSigner())
    with pytest.raises(ValueError, match="nonce"):
        signer.sign(SignatureProfile.SAFE_READ, inputs("nonce"), 10, 70)
    with pytest.raises(ValueError, match="nonce"):
        signer.sign(SignatureProfile.BODYLESS_NONCE_MUTATION, inputs(), 10, 70)


def test_base_refuses_lifetime_longer_than_three_hundred_seconds() -> None:
    """The wire builder keeps the gateway limit independently of client settings."""
    with pytest.raises(ValueError, match="300"):
        PartnerRequestSigner(StubSigner()).sign(SignatureProfile.SAFE_READ, inputs(), 10, 311)


def test_authority_drops_only_its_scheme_default_port() -> None:
    """Authority canonicalization follows the request scheme before signing bytes."""
    http = SignatureInputs("get", "PARTNERS.ANIS.LY:80", "/v1/profile", "", "date", scheme="http")
    https = SignatureInputs("get", "partners.anis.ly:80", "/v1/profile", "", "date", scheme="https")
    assert http.authority == "partners.anis.ly"
    assert https.authority == "partners.anis.ly:80"
