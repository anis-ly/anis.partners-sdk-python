"""Closed route inventory used to detect drift from the published partner contract."""

from dataclasses import dataclass

from anis_partners.signing.signature_profile import SignatureProfile


@dataclass(frozen=True, slots=True)
class PartnerRoute:
    """Keep method, template, and signing profile together so path shape cannot choose security policy."""

    method: str
    template: str
    profile: SignatureProfile | None


PARTNER_ROUTES: tuple[PartnerRoute, ...] = (
    PartnerRoute("GET", "/v1/profile", SignatureProfile.SAFE_READ),
    PartnerRoute("GET", "/v1/wallets", SignatureProfile.SAFE_READ),
    PartnerRoute("GET", "/v1/wallets/{walletId}", SignatureProfile.SAFE_READ),
    PartnerRoute("GET", "/v1/wallets/{walletId}/catalog/categories", SignatureProfile.SAFE_READ),
    PartnerRoute(
        "GET",
        "/v1/wallets/{walletId}/catalog/categories/{categoryId}/subcategories",
        SignatureProfile.SAFE_READ,
    ),
    PartnerRoute("GET", "/v1/wallets/{walletId}/catalog/subcategories/{subcategoryId}", SignatureProfile.SAFE_READ),
    PartnerRoute(
        "GET",
        "/v1/wallets/{walletId}/catalog/subcategories/{subcategoryId}/cards",
        SignatureProfile.SAFE_READ,
    ),
    PartnerRoute("POST", "/v1/wallets/{walletId}/orders", SignatureProfile.ORDER_MUTATION),
    PartnerRoute("GET", "/v1/orders/{operationId}", SignatureProfile.SAFE_READ),
    PartnerRoute("GET", "/v1/wallets/{walletId}/cards", SignatureProfile.SAFE_READ),
    PartnerRoute("GET", "/v1/wallets/{walletId}/cards/{soldCardId}", SignatureProfile.SAFE_READ),
    PartnerRoute("POST", "/v1/wallets/{walletId}/cards/{soldCardId}/reveal", SignatureProfile.BODYLESS_NONCE_MUTATION),
    PartnerRoute(
        "POST",
        "/v1/wallets/{walletId}/invoices/{invoiceId}/cards/reveal",
        SignatureProfile.BODYLESS_NONCE_MUTATION,
    ),
    PartnerRoute("POST", "/v1/diagnostics/signature", SignatureProfile.BODYLESS_NONCE_MUTATION),
    PartnerRoute("GET", "/v1/enrollments/{invitationId}", None),
    PartnerRoute("POST", "/v1/enrollments/{invitationId}/keys", None),
    PartnerRoute("POST", "/v1/enrollments/{invitationId}/proof", None),
    PartnerRoute("GET", "/v1/enrollments/{invitationId}/status", None),
    PartnerRoute("GET", "/.well-known/partner-signing-keys.json", None),
)
