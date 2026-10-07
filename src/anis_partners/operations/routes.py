"""Closed route inventory used to detect drift from the published partner contract."""

from dataclasses import dataclass

from anis_partners.signing.signature_profile import SignatureProfile


@dataclass(frozen=True, slots=True)
class PartnerRoute:
    """Keep method, template, signing profile, and answer signing together so path shape cannot choose policy."""

    method: str
    template: str
    profile: SignatureProfile | None
    #: Whether Anis signs every answer on this route, success and refusal alike. A signed route's answer is
    #: verified and refused without a valid signature; an unsigned route's answer is read without verification.
    #: Defaults to signed so a route added without a decision fails closed.
    signs_response: bool = True


PARTNER_ROUTES: tuple[PartnerRoute, ...] = (
    PartnerRoute("GET", "/v1/profile", SignatureProfile.SAFE_READ, signs_response=False),
    PartnerRoute("GET", "/v1/wallets", SignatureProfile.SAFE_READ, signs_response=False),
    PartnerRoute("GET", "/v1/wallets/{walletId}", SignatureProfile.SAFE_READ, signs_response=False),
    PartnerRoute("GET", "/v1/wallets/{walletId}/catalog/categories", SignatureProfile.SAFE_READ, signs_response=False),
    PartnerRoute(
        "GET",
        "/v1/wallets/{walletId}/catalog/categories/{categoryId}/subcategories",
        SignatureProfile.SAFE_READ,
        signs_response=False,
    ),
    PartnerRoute(
        "GET",
        "/v1/wallets/{walletId}/catalog/subcategories/{subcategoryId}",
        SignatureProfile.SAFE_READ,
        signs_response=False,
    ),
    PartnerRoute(
        "GET",
        "/v1/wallets/{walletId}/catalog/subcategories/{subcategoryId}/cards",
        SignatureProfile.SAFE_READ,
        signs_response=False,
    ),
    PartnerRoute("POST", "/v1/wallets/{walletId}/orders", SignatureProfile.ORDER_MUTATION, signs_response=True),
    PartnerRoute("GET", "/v1/orders/{operationId}", SignatureProfile.SAFE_READ, signs_response=True),
    PartnerRoute("GET", "/v1/wallets/{walletId}/cards", SignatureProfile.SAFE_READ, signs_response=False),
    PartnerRoute("GET", "/v1/wallets/{walletId}/cards/{soldCardId}", SignatureProfile.SAFE_READ, signs_response=False),
    PartnerRoute(
        "POST",
        "/v1/wallets/{walletId}/cards/{soldCardId}/reveal",
        SignatureProfile.BODYLESS_NONCE_MUTATION,
        signs_response=True,
    ),
    PartnerRoute(
        "POST",
        "/v1/wallets/{walletId}/invoices/{invoiceId}/cards/reveal",
        SignatureProfile.BODYLESS_NONCE_MUTATION,
        signs_response=True,
    ),
    PartnerRoute("POST", "/v1/diagnostics/signature", SignatureProfile.BODYLESS_NONCE_MUTATION, signs_response=True),
    PartnerRoute("GET", "/v1/enrollments/{invitationId}", None, signs_response=True),
    PartnerRoute("POST", "/v1/enrollments/{invitationId}/keys", None, signs_response=True),
    PartnerRoute("POST", "/v1/enrollments/{invitationId}/proof", None, signs_response=True),
    PartnerRoute("GET", "/v1/enrollments/{invitationId}/status", None, signs_response=True),
    PartnerRoute("GET", "/.well-known/partner-signing-keys.json", None, signs_response=False),
)
