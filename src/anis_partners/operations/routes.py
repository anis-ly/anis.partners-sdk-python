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
    route_id: str | None = None
    scope: str | None = None
    wallet_bound: bool = False


PARTNER_ROUTES: tuple[PartnerRoute, ...] = (
    PartnerRoute("POST", "/v1/application/suspend", SignatureProfile.BODYLESS_NONCE_MUTATION),
    PartnerRoute("POST", "/v1/keys/{keyId}/revoke", SignatureProfile.BODYLESS_NONCE_MUTATION),
    PartnerRoute(
        "GET", "/v1/wallets/{walletId}/catalog/cards/{cardId}", SignatureProfile.SAFE_READ, signs_response=False
    ),
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
    PartnerRoute("GET", "/v1/wallets/{walletId}/owned-cards", SignatureProfile.SAFE_READ, signs_response=False),
    PartnerRoute(
        "GET", "/v1/wallets/{walletId}/owned-cards/{soldCardId}", SignatureProfile.SAFE_READ, signs_response=False
    ),
    PartnerRoute(
        "POST",
        "/v1/wallets/{walletId}/owned-cards/{soldCardId}/reveal",
        SignatureProfile.BODYLESS_NONCE_MUTATION,
        signs_response=True,
    ),
    PartnerRoute(
        "POST",
        "/v1/wallets/{walletId}/invoices/{invoiceId}/owned-cards/reveal",
        SignatureProfile.BODYLESS_NONCE_MUTATION,
        signs_response=True,
    ),
    PartnerRoute("POST", "/v1/diagnostics/signature", SignatureProfile.BODYLESS_NONCE_MUTATION, signs_response=True),
    PartnerRoute("GET", "/v1/enrollments/{invitationId}", None, signs_response=True),
    PartnerRoute("POST", "/v1/enrollments/{invitationId}/keys", None, signs_response=True),
    PartnerRoute("POST", "/v1/enrollments/{invitationId}/proof", None, signs_response=True),
    PartnerRoute("GET", "/v1/enrollments/{invitationId}/status", None, signs_response=True),
    PartnerRoute("GET", "/.well-known/partner-signing-keys.json", None, signs_response=False),
    PartnerRoute(
        "GET",
        "/v1/wallets/{walletId}/meter-packages",
        SignatureProfile.SAFE_READ,
        signs_response=False,
        route_id="partner.meter-packages.getMeterPackages",
        scope="meter_charges:read",
        wallet_bound=True,
    ),
    PartnerRoute(
        "GET",
        "/v1/wallets/{walletId}/meter-charges",
        SignatureProfile.SAFE_READ,
        signs_response=False,
        route_id="partner.meter-charges.getMeterCharges",
        scope="meter_charges:read",
        wallet_bound=True,
    ),
    PartnerRoute(
        "POST",
        "/v1/wallets/{walletId}/meter-charges",
        SignatureProfile.ORDER_MUTATION,
        signs_response=True,
        route_id="partner.meter-charges.create",
        scope="meter_charges:create",
        wallet_bound=True,
    ),
    PartnerRoute(
        "GET",
        "/v1/meter-charges/{operationId}",
        SignatureProfile.SAFE_READ,
        signs_response=True,
        route_id="partner.meter-charges.read",
        scope="meter_charges:read",
        wallet_bound=False,
    ),
    PartnerRoute(
        "GET",
        "/v1/wallets/{walletId}/direct-recharge-products",
        SignatureProfile.SAFE_READ,
        signs_response=False,
        route_id="partner.direct-recharge-products.getDirectRechargeProducts",
        scope="direct_recharges:read",
        wallet_bound=True,
    ),
    PartnerRoute(
        "GET",
        "/v1/wallets/{walletId}/direct-recharge-products/{productId}",
        SignatureProfile.SAFE_READ,
        signs_response=False,
        route_id="partner.direct-recharge-products.read",
        scope="direct_recharges:read",
        wallet_bound=True,
    ),
    PartnerRoute(
        "GET",
        "/v1/wallets/{walletId}/direct-recharge-products/{productId}/locations",
        SignatureProfile.SAFE_READ,
        signs_response=False,
        route_id="partner.direct-recharge-products.locations.getDirectRechargeProductLocations",
        scope="direct_recharges:read",
        wallet_bound=True,
    ),
    PartnerRoute(
        "GET",
        "/v1/wallets/{walletId}/direct-recharge-products/{productId}/quote",
        SignatureProfile.SAFE_READ,
        signs_response=False,
        route_id="partner.direct-recharge-products.quote",
        scope="direct_recharges:read",
        wallet_bound=True,
    ),
    PartnerRoute(
        "GET",
        "/v1/wallets/{walletId}/direct-recharges",
        SignatureProfile.SAFE_READ,
        signs_response=False,
        route_id="partner.direct-recharges.getDirectRecharges",
        scope="direct_recharges:read",
        wallet_bound=True,
    ),
    PartnerRoute(
        "POST",
        "/v1/wallets/{walletId}/direct-recharges",
        SignatureProfile.ORDER_MUTATION,
        signs_response=True,
        route_id="partner.direct-recharges.create",
        scope="direct_recharges:create",
        wallet_bound=True,
    ),
    PartnerRoute(
        "GET",
        "/v1/direct-recharges/{operationId}",
        SignatureProfile.SAFE_READ,
        signs_response=True,
        route_id="partner.direct-recharges.read",
        scope="direct_recharges:read",
        wallet_bound=False,
    ),
    PartnerRoute(
        "PATCH",
        "/v1/direct-recharges/{operationId}/recipient",
        SignatureProfile.BODYLESS_NONCE_MUTATION,
        signs_response=True,
        route_id="partner.direct-recharges.recipient.update",
        scope="direct_recharges:create",
        wallet_bound=False,
    ),
    PartnerRoute(
        "GET",
        "/v1/webhook-endpoint",
        SignatureProfile.SAFE_READ,
        signs_response=False,
        route_id="partner.webhook-endpoint.read",
        scope=None,
        wallet_bound=False,
    ),
    PartnerRoute(
        "PUT",
        "/v1/webhook-endpoint",
        SignatureProfile.BODYLESS_NONCE_MUTATION,
        signs_response=True,
        route_id="partner.webhook-endpoint.update",
        scope=None,
        wallet_bound=False,
    ),
    PartnerRoute(
        "POST",
        "/v1/webhook-endpoint/test",
        SignatureProfile.BODYLESS_NONCE_MUTATION,
        signs_response=True,
        route_id="partner.webhook-endpoint.test",
        scope=None,
        wallet_bound=False,
    ),
    PartnerRoute(
        "GET",
        "/v1/webhook-events",
        SignatureProfile.SAFE_READ,
        signs_response=False,
        route_id="partner.webhook-events.getWebhookEvents",
        scope=None,
        wallet_bound=False,
    ),
    PartnerRoute(
        "POST",
        "/v1/webhook-events/{eventId}/redeliver",
        SignatureProfile.BODYLESS_NONCE_MUTATION,
        signs_response=True,
        route_id="partner.webhook-events.redeliver",
        scope=None,
        wallet_bound=False,
    ),
)
