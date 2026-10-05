"""Native object inspection must not expose credentials or request authorization material."""

from uuid import UUID

from anis_partners.enrollment.client import AnisEnrollmentClient
from anis_partners.models import Order, OrderCompleted, RevealedCredential, RevealedCredentialCollection
from anis_partners.operations.transport import RequestSpec
from anis_partners.signing.signed_request_headers import SignedRequestHeaders


def test_revealed_credentials_stay_redacted_inside_order_and_collection_repr() -> None:
    """Nested dataclass representations preserve useful structure without revealing voucher or serial values."""
    credential = RevealedCredential(UUID(int=1), "serial-secret", "voucher-secret")
    order = Order(sold_cards=(credential,))
    captured = repr((OrderCompleted(order), RevealedCredentialCollection((credential,))))
    assert "<redacted>" in captured
    assert "serial-secret" not in captured
    assert "voucher-secret" not in captured


def test_signed_request_header_repr_redacts_signature_nonce_and_base() -> None:
    """A signature result can be inspected without exposing replayable signing material."""
    headers = SignedRequestHeaders(
        "signature-input-secret",
        "signature-secret",
        "2026-10-05T00:00:00Z",
        None,
        "nonce-secret",
        None,
        b"signature-base-secret",
    )
    captured = repr(headers)
    for secret in ("signature-input-secret", "signature-secret", "nonce-secret", "signature-base-secret"):
        assert secret not in captured
    assert "<redacted>" in captured


def test_enrollment_token_stays_redacted_in_client_and_request_repr() -> None:
    """One-time enrollment authorization stays out of client and prepared-request inspection."""
    client = AnisEnrollmentClient("https://partners.test", UUID(int=2), "enrollment-token-secret")
    try:
        request = RequestSpec(
            "GET",
            "/v1/enrollments/{id}",
            "/v1/enrollments/2",
            None,
            authorization="Enrollment enrollment-token-secret",
        )
        captured = repr((client, request))
        assert "<redacted>" in captured
        assert "enrollment-token-secret" not in captured
    finally:
        client.close()
