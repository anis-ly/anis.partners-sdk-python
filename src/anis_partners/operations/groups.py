"""Synchronous and asynchronous operation groups that share paths and outcome decisions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import replace
from datetime import timedelta
from typing import TypeVar
from urllib.parse import quote, urlencode
from uuid import UUID

import httpx

from anis_partners._internal.uuid import parse as parse_uuid
from anis_partners.errors import AnisApiError, MalformedResponseError
from anis_partners.errors.base import KeyDocumentUnavailableError
from anis_partners.models import (
    ApplicationSuspended,
    CatalogueCard,
    CatalogueCategory,
    CatalogueSubcategory,
    CreateOrderRequest,
    KeyRevoked,
    MaskedCard,
    Order,
    OrderOutcomeUnknown,
    OrderResult,
    Page,
    PartnerProfile,
    RevealedCredential,
    RevealedCredentialCollection,
    SignatureDiagnostic,
    Wallet,
)
from anis_partners.models._json import object_data
from anis_partners.models.direct_recharge_products import (
    DirectRechargeAmountIn,
    DirectRechargeLocation,
    DirectRechargeLocationsQuery,
    DirectRechargeProduct,
    DirectRechargeProductsQuery,
    DirectRechargeProductSummary,
    DirectRechargeQuote,
)
from anis_partners.models.direct_recharges import (
    CreateDirectRechargeRequest,
    DirectRecharge,
    DirectRechargeAccepted,
    DirectRechargesQuery,
    DirectRechargeSummary,
    UpdateDirectRechargeRecipientRequest,
)
from anis_partners.models.meter_charges import (
    CreateMeterChargeRequest,
    MeterCharge,
    MeterChargeAccepted,
    MeterChargesQuery,
    MeterChargeSummary,
    MeterPackage,
)
from anis_partners.models.product_results import (
    DirectRechargeNotPlaced,
    DirectRechargeOutcomeUnknown,
    DirectRechargeProcessing,
    DirectRechargeResult,
    MeterChargeNotPlaced,
    MeterChargeOutcomeUnknown,
    MeterChargeResult,
)
from anis_partners.models.webhooks import (
    SetWebhookEndpointRequest,
    WebhookEndpoint,
    WebhookEvent,
    WebhookEventAccepted,
    WebhookEventsQuery,
)
from anis_partners.operations.routes import PARTNER_ROUTES
from anis_partners.operations.transport import (
    AsyncTransport,
    RequestCore,
    RequestSpec,
    SyncTransport,
    classify_direct_recharge,
    classify_meter_charge,
    classify_order,
    classify_refusal,
    product_refusal_delay,
    product_refusal_is_final,
    read_direct_recharge,
    read_meter_charge,
    read_recipient_update,
    record_order_outcome,
    record_unknown_order,
    validate_order,
)
from anis_partners.signing.errors import RequestSigningError
from anis_partners.verification.errors import UnverifiableResponseError

T = TypeVar("T")


def _id(value: UUID | str, argument_name: str) -> UUID:
    """Parse caller identifiers before building request paths or idempotency headers."""
    return parse_uuid(value, argument_name)


def _spec(
    core: RequestCore,
    method: str,
    route: str,
    path: str,
    body: object | None = None,
    operation_id: UUID | None = None,
    authorization: str | None = None,
) -> RequestSpec:
    """Read request signing and answer verification from the frozen route table, never from method, path, or answer."""
    try:
        descriptor = next((item for item in PARTNER_ROUTES if item.template == route and item.method == method), None)
        if descriptor is None:
            raise ValueError("The route is not in the published partner route table.")
        return RequestSpec(
            method,
            route,
            path,
            descriptor.profile,
            core.body_bytes(body),
            str(operation_id) if operation_id is not None else None,
            authorization,
            descriptor.signs_response,
        )
    except RequestSigningError:
        raise
    except Exception as exc:
        raise RequestSigningError("The request was not sent because it could not be prepared.") from exc


def _page_reader(reader: Callable[[object], T]) -> Callable[[object], Page[T]]:
    """Keep each page's item schema attached so malformed entries fail before leaving the SDK."""
    return lambda data: Page.from_json(data, reader)


def _cursor(path: str, cursor: str | None) -> str:
    return path if not cursor else f"{path}?cursor={quote(cursor, safe='-_.~')}"


def _next_cursor(cursor: str | None, seen: set[str]) -> str | None:
    """Refuse cursor cycles so a changing multi-page response cannot make an iterator loop forever."""
    if cursor is None:
        return None
    if cursor in seen:
        raise MalformedResponseError("Anis returned a repeated cursor while paging.")
    seen.add(cursor)
    return cursor


def _reason(reason: str) -> dict[str, str]:
    """Require a bounded stop reason before dispatching an irreversible self-service request."""
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
        raise ValueError("reason must contain 1 to 500 characters after trimming.")
    return {"reason": reason.strip()}


class SyncAccessOperations:
    """Stop access for this admitted application through signed, nonce-protected requests."""

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def suspend_application(self, reason: str) -> ApplicationSuspended:
        """Submit a required reason and return the verified current stop state."""
        route = "/v1/application/suspend"
        spec = _spec(self._transport.core, "POST", route, route, _reason(reason))
        return (self._transport.send(spec, ApplicationSuspended.from_json))[0]

    def revoke_key(self, key_id: UUID | str, reason: str) -> KeyRevoked:
        """Submit a required reason and return the verified current stop state."""
        key = _id(key_id, "key_id")
        route = "/v1/keys/{keyId}/revoke"
        spec = _spec(self._transport.core, "POST", route, f"/v1/keys/{key}/revoke", _reason(reason))
        return (self._transport.send(spec, KeyRevoked.from_json))[0]


class AsyncAccessOperations:
    """Stop access for this admitted application through signed, nonce-protected requests."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def suspend_application(self, reason: str) -> ApplicationSuspended:
        """Submit a required reason and return the verified current stop state."""
        route = "/v1/application/suspend"
        spec = _spec(self._transport.core, "POST", route, route, _reason(reason))
        return (await self._transport.send(spec, ApplicationSuspended.from_json))[0]

    async def revoke_key(self, key_id: UUID | str, reason: str) -> KeyRevoked:
        """Submit a required reason and return the verified current stop state."""
        key = _id(key_id, "key_id")
        route = "/v1/keys/{keyId}/revoke"
        spec = _spec(self._transport.core, "POST", route, f"/v1/keys/{key}/revoke", _reason(reason))
        return (await self._transport.send(spec, KeyRevoked.from_json))[0]


class SyncProfileOperations:
    """Read the live application profile so current policy scopes are not mistaken for cached grants."""

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def get(self) -> PartnerProfile:
        """Read this application's identity and effective scopes from the current policy."""
        spec = _spec(self._transport.core, "GET", "/v1/profile", "/v1/profile")
        return self._transport.send(spec, PartnerProfile.from_json)[0]


class SyncWalletOperations:
    """Read eligible wallets and expose cursor paging without caching live grants."""

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def list_page(self, cursor: str | None = None) -> Page[Wallet]:
        """Read one wallet page when the caller manages the continuation cursor."""
        spec = _spec(self._transport.core, "GET", "/v1/wallets", _cursor("/v1/wallets", cursor))
        return self._transport.send(spec, _page_reader(Wallet.from_json))[0]

    def list(self) -> Iterator[Wallet]:
        """Yield every granted wallet so callers cannot accidentally stop after the first page."""
        cursor = None
        seen: set[str] = set()
        while True:
            page = self.list_page(cursor)
            yield from page.items
            cursor = _next_cursor(page.next_cursor, seen)
            if not cursor:
                break

    def get(self, wallet_id: UUID | str) -> Wallet:
        """Read one wallet by its caller-supplied id."""
        identifier = _id(wallet_id, "wallet_id")
        route = "/v1/wallets/{walletId}"
        spec = _spec(self._transport.core, "GET", route, f"/v1/wallets/{identifier}")
        return self._transport.send(spec, Wallet.from_json)[0]


class SyncCatalogueOperations:
    """Read wallet-priced catalogue entries and preserve Anis's continuation cursors."""

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def get_card(self, wallet_id: UUID | str, card_id: UUID | str) -> CatalogueCard:
        """Read one catalogue card priced for the selected wallet."""
        wallet, card = _id(wallet_id, "wallet_id"), _id(card_id, "card_id")
        route = "/v1/wallets/{walletId}/catalog/cards/{cardId}"
        spec = _spec(self._transport.core, "GET", route, f"/v1/wallets/{wallet}/catalog/cards/{card}")
        return (self._transport.send(spec, CatalogueCard.from_json))[0]

    def list_categories_page(self, wallet_id: UUID | str, cursor: str | None = None) -> Page[CatalogueCategory]:
        """Read one category page for the selected wallet."""
        wallet = _id(wallet_id, "wallet_id")
        route = "/v1/wallets/{walletId}/catalog/categories"
        spec = _spec(self._transport.core, "GET", route, _cursor(f"/v1/wallets/{wallet}/catalog/categories", cursor))
        return self._transport.send(spec, _page_reader(CatalogueCategory.from_json))[0]

    def list_categories(self, wallet_id: UUID | str) -> Iterator[CatalogueCategory]:
        """Yield all categories so a caller does not silently omit later pages."""
        cursor = None
        seen: set[str] = set()
        while True:
            page = self.list_categories_page(wallet_id, cursor)
            yield from page.items
            cursor = _next_cursor(page.next_cursor, seen)
            if not cursor:
                break

    def list_subcategories_page(
        self, wallet_id: UUID | str, category_id: UUID | str, cursor: str | None = None
    ) -> Page[CatalogueSubcategory]:
        """Read one subcategory page under its wallet and category."""
        wallet, category = _id(wallet_id, "wallet_id"), _id(category_id, "category_id")
        route = "/v1/wallets/{walletId}/catalog/categories/{categoryId}/subcategories"
        path = _cursor(f"/v1/wallets/{wallet}/catalog/categories/{category}/subcategories", cursor)
        return self._transport.send(
            _spec(self._transport.core, "GET", route, path), _page_reader(CatalogueSubcategory.from_json)
        )[0]

    def list_subcategories(self, wallet_id: UUID | str, category_id: UUID | str) -> Iterator[CatalogueSubcategory]:
        """Yield all subcategories so cursor handling remains safe by default."""
        cursor = None
        seen: set[str] = set()
        while True:
            page = self.list_subcategories_page(wallet_id, category_id, cursor)
            yield from page.items
            cursor = _next_cursor(page.next_cursor, seen)
            if not cursor:
                break

    def get_subcategory(self, wallet_id: UUID | str, subcategory_id: UUID | str) -> CatalogueSubcategory:
        """Read one subcategory within the selected wallet."""
        wallet, subcategory = _id(wallet_id, "wallet_id"), _id(subcategory_id, "subcategory_id")
        route = "/v1/wallets/{walletId}/catalog/subcategories/{subcategoryId}"
        spec = _spec(self._transport.core, "GET", route, f"/v1/wallets/{wallet}/catalog/subcategories/{subcategory}")
        return self._transport.send(spec, CatalogueSubcategory.from_json)[0]

    def list_cards_page(
        self, wallet_id: UUID | str, subcategory_id: UUID | str, cursor: str | None = None
    ) -> Page[CatalogueCard]:
        """Read one wallet-priced card page under a catalogue subcategory."""
        wallet, subcategory = _id(wallet_id, "wallet_id"), _id(subcategory_id, "subcategory_id")
        route = "/v1/wallets/{walletId}/catalog/subcategories/{subcategoryId}/cards"
        path = _cursor(f"/v1/wallets/{wallet}/catalog/subcategories/{subcategory}/cards", cursor)
        return self._transport.send(
            _spec(self._transport.core, "GET", route, path), _page_reader(CatalogueCard.from_json)
        )[0]

    def list_cards(self, wallet_id: UUID | str, subcategory_id: UUID | str) -> Iterator[CatalogueCard]:
        """Yield all listed cards so later catalogue pages remain visible to the buyer."""
        cursor = None
        seen: set[str] = set()
        while True:
            page = self.list_cards_page(wallet_id, subcategory_id, cursor)
            yield from page.items
            cursor = _next_cursor(page.next_cursor, seen)
            if not cursor:
                break


class SyncOwnedCardOperations:
    """Read masked card projections, and reveal credentials only through explicit, signed, verified calls."""

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def list_page(self, wallet_id: UUID | str, cursor: str | None = None) -> Page[MaskedCard]:
        """Read one masked-card page without exposing credentials in list results."""
        wallet = _id(wallet_id, "wallet_id")
        route = "/v1/wallets/{walletId}/owned-cards"
        spec = _spec(self._transport.core, "GET", route, _cursor(f"/v1/wallets/{wallet}/owned-cards", cursor))
        return self._transport.send(spec, _page_reader(MaskedCard.from_json))[0]

    def list(self, wallet_id: UUID | str) -> Iterator[MaskedCard]:
        """Yield every masked card across all cursor pages."""
        cursor = None
        seen: set[str] = set()
        while True:
            page = self.list_page(wallet_id, cursor)
            yield from page.items
            cursor = _next_cursor(page.next_cursor, seen)
            if not cursor:
                break

    def get(self, wallet_id: UUID | str, sold_card_id: UUID | str) -> MaskedCard:
        """Read one masked card before deciding whether its credential should be revealed."""
        wallet, sold = _id(wallet_id, "wallet_id"), _id(sold_card_id, "sold_card_id")
        route = "/v1/wallets/{walletId}/owned-cards/{soldCardId}"
        return self._transport.send(
            _spec(self._transport.core, "GET", route, f"/v1/wallets/{wallet}/owned-cards/{sold}"), MaskedCard.from_json
        )[0]

    def reveal(self, wallet_id: UUID | str, sold_card_id: UUID | str) -> RevealedCredential:
        """Reveal one credential only on an explicit call because plaintext cannot be recovered from masked data."""
        wallet, sold = _id(wallet_id, "wallet_id"), _id(sold_card_id, "sold_card_id")
        route = "/v1/wallets/{walletId}/owned-cards/{soldCardId}/reveal"
        return self._transport.send(
            _spec(self._transport.core, "POST", route, f"/v1/wallets/{wallet}/owned-cards/{sold}/reveal"),
            RevealedCredential.from_json,
        )[0]

    def reveal_invoice(self, wallet_id: UUID | str, invoice_id: UUID | str) -> RevealedCredentialCollection:
        """Reveal an invoice atomically so callers never mistake a partial set for the complete purchase."""
        wallet, invoice = _id(wallet_id, "wallet_id"), _id(invoice_id, "invoice_id")
        route = "/v1/wallets/{walletId}/invoices/{invoiceId}/owned-cards/reveal"
        path = f"/v1/wallets/{wallet}/invoices/{invoice}/owned-cards/reveal"
        return self._transport.send(
            _spec(self._transport.core, "POST", route, path), RevealedCredentialCollection.from_json
        )[0]


class SyncDiagnosticsOperations:
    """Expose the side-effect-free signature check that reports the gateway's canonical request facts."""

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def check_signature(self) -> SignatureDiagnostic:
        """Send the exact empty object required by the diagnostic route and return verified facts."""
        route = "/v1/diagnostics/signature"
        spec = _spec(self._transport.core, "POST", route, route, {})
        return self._transport.send(spec, SignatureDiagnostic.from_json)[0]


class SyncOrderOperations:
    """Create and resume orders under caller-owned ids so retries cannot silently purchase twice."""

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def create(self, *, wallet_id: UUID | str, operation_id: UUID | str, order: CreateOrderRequest) -> OrderResult:
        """Create one order after local quantity, price, currency, and total checks pass."""
        return self._send(wallet_id, operation_id, order, False)

    def resume(self, *, wallet_id: UUID | str, operation_id: UUID | str, order: CreateOrderRequest) -> OrderResult:
        """Repeat the exact order body with the same operation id to recover an unknown outcome."""
        return self._send(wallet_id, operation_id, order, True)

    def get(self, operation_id: UUID | str) -> Order:
        """Read order state without dispatching recovery or revealing credentials."""
        identifier = _id(operation_id, "operation_id")
        route = "/v1/orders/{operationId}"
        return self._transport.send(
            _spec(self._transport.core, "GET", route, f"/v1/orders/{identifier}"), Order.from_json
        )[0]

    def _send(
        self, wallet_id: UUID | str, operation_id: UUID | str, order: CreateOrderRequest, resuming: bool
    ) -> OrderResult:
        wallet, operation = _id(wallet_id, "wallet_id"), _id(operation_id, "operation_id")
        if order is None:
            raise TypeError("order cannot be None.")
        validate_order(order)
        route = "/v1/wallets/{walletId}/orders"
        spec = _spec(self._transport.core, "POST", route, f"/v1/wallets/{wallet}/orders", order, operation)
        reason: str | None = None
        try:
            model, response, _ = self._transport.send(spec, Order.from_json)
            outcome = classify_order(model, response)
        except AnisApiError as exc:
            outcome = classify_refusal(exc, operation, resuming)
        except RequestSigningError:
            raise
        except KeyboardInterrupt:
            record_unknown_order(self._transport.core, str(operation), "canceled")
            raise
        except KeyDocumentUnavailableError as exc:
            outcome = OrderOutcomeUnknown(operation, timedelta(seconds=5), exc)
            reason = exc.error_type
        except Exception as exc:
            outcome = OrderOutcomeUnknown(operation, timedelta(seconds=5), exc)
            if isinstance(exc, UnverifiableResponseError):
                reason = "unverifiable"
            elif isinstance(exc, (httpx.TimeoutException, TimeoutError, asyncio.TimeoutError)):
                reason = "timeout"
            elif isinstance(exc, httpx.TransportError):
                reason = "connection"
            else:
                reason = "other"
        record_order_outcome(self._transport.core, outcome, str(operation), reason)
        return outcome


class AsyncProfileOperations:
    """Read the current profile asynchronously without caching the effective policy."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def get(self) -> PartnerProfile:
        """Read this application's identity and live scopes."""
        return (
            await self._transport.send(
                _spec(self._transport.core, "GET", "/v1/profile", "/v1/profile"), PartnerProfile.from_json
            )
        )[0]


class AsyncWalletOperations:
    """Read eligible wallets asynchronously with both page and all-page forms."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def list_page(self, cursor: str | None = None) -> Page[Wallet]:
        """Read one page for hosts that manage cursors themselves."""
        spec = _spec(self._transport.core, "GET", "/v1/wallets", _cursor("/v1/wallets", cursor))
        return (await self._transport.send(spec, _page_reader(Wallet.from_json)))[0]

    async def list(self) -> AsyncIterator[Wallet]:
        """Yield all wallets so later pages are not omitted by default."""
        cursor = None
        seen: set[str] = set()
        while True:
            page = await self.list_page(cursor)
            for wallet in page.items:
                yield wallet
            cursor = _next_cursor(page.next_cursor, seen)
            if not cursor:
                break

    async def get(self, wallet_id: UUID | str) -> Wallet:
        """Read one wallet by id."""
        identifier = _id(wallet_id, "wallet_id")
        route = "/v1/wallets/{walletId}"
        return (
            await self._transport.send(
                _spec(self._transport.core, "GET", route, f"/v1/wallets/{identifier}"), Wallet.from_json
            )
        )[0]


class AsyncCatalogueOperations:
    """Read the wallet-priced catalogue through asynchronous page and iterator methods."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def get_card(self, wallet_id: UUID | str, card_id: UUID | str) -> CatalogueCard:
        """Read one catalogue card priced for the selected wallet."""
        wallet, card = _id(wallet_id, "wallet_id"), _id(card_id, "card_id")
        route = "/v1/wallets/{walletId}/catalog/cards/{cardId}"
        spec = _spec(self._transport.core, "GET", route, f"/v1/wallets/{wallet}/catalog/cards/{card}")
        return (await self._transport.send(spec, CatalogueCard.from_json))[0]

    async def list_categories_page(self, wallet_id: UUID | str, cursor: str | None = None) -> Page[CatalogueCategory]:
        """Read one category page for a wallet."""
        wallet = _id(wallet_id, "wallet_id")
        route = "/v1/wallets/{walletId}/catalog/categories"
        return (
            await self._transport.send(
                _spec(self._transport.core, "GET", route, _cursor(f"/v1/wallets/{wallet}/catalog/categories", cursor)),
                _page_reader(CatalogueCategory.from_json),
            )
        )[0]

    async def list_categories(self, wallet_id: UUID | str) -> AsyncIterator[CatalogueCategory]:
        """Yield every category across all server pages."""
        cursor = None
        seen: set[str] = set()
        while True:
            page = await self.list_categories_page(wallet_id, cursor)
            for item in page.items:
                yield item
            cursor = _next_cursor(page.next_cursor, seen)
            if not cursor:
                break

    async def list_subcategories_page(
        self, wallet_id: UUID | str, category_id: UUID | str, cursor: str | None = None
    ) -> Page[CatalogueSubcategory]:
        """Read one subcategory page under a category."""
        wallet, category = _id(wallet_id, "wallet_id"), _id(category_id, "category_id")
        route = "/v1/wallets/{walletId}/catalog/categories/{categoryId}/subcategories"
        path = _cursor(f"/v1/wallets/{wallet}/catalog/categories/{category}/subcategories", cursor)
        return (
            await self._transport.send(
                _spec(self._transport.core, "GET", route, path), _page_reader(CatalogueSubcategory.from_json)
            )
        )[0]

    async def list_subcategories(
        self, wallet_id: UUID | str, category_id: UUID | str
    ) -> AsyncIterator[CatalogueSubcategory]:
        """Yield all subcategories so clients do not overlook later pages."""
        cursor = None
        seen: set[str] = set()
        while True:
            page = await self.list_subcategories_page(wallet_id, category_id, cursor)
            for item in page.items:
                yield item
            cursor = _next_cursor(page.next_cursor, seen)
            if not cursor:
                break

    async def get_subcategory(self, wallet_id: UUID | str, subcategory_id: UUID | str) -> CatalogueSubcategory:
        """Read a single subcategory."""
        wallet, subcategory = _id(wallet_id, "wallet_id"), _id(subcategory_id, "subcategory_id")
        route = "/v1/wallets/{walletId}/catalog/subcategories/{subcategoryId}"
        return (
            await self._transport.send(
                _spec(self._transport.core, "GET", route, f"/v1/wallets/{wallet}/catalog/subcategories/{subcategory}"),
                CatalogueSubcategory.from_json,
            )
        )[0]

    async def list_cards_page(
        self, wallet_id: UUID | str, subcategory_id: UUID | str, cursor: str | None = None
    ) -> Page[CatalogueCard]:
        """Read one page of cards priced for the selected wallet."""
        wallet, subcategory = _id(wallet_id, "wallet_id"), _id(subcategory_id, "subcategory_id")
        route = "/v1/wallets/{walletId}/catalog/subcategories/{subcategoryId}/cards"
        path = _cursor(f"/v1/wallets/{wallet}/catalog/subcategories/{subcategory}/cards", cursor)
        return (
            await self._transport.send(
                _spec(self._transport.core, "GET", route, path), _page_reader(CatalogueCard.from_json)
            )
        )[0]

    async def list_cards(self, wallet_id: UUID | str, subcategory_id: UUID | str) -> AsyncIterator[CatalogueCard]:
        """Yield all catalogue cards across every cursor page."""
        cursor = None
        seen: set[str] = set()
        while True:
            page = await self.list_cards_page(wallet_id, subcategory_id, cursor)
            for item in page.items:
                yield item
            cursor = _next_cursor(page.next_cursor, seen)
            if not cursor:
                break


class AsyncOwnedCardOperations:
    """Read masked owned cards asynchronously and reveal credentials only on explicit calls."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def list_page(self, wallet_id: UUID | str, cursor: str | None = None) -> Page[MaskedCard]:
        """Read one masked card page."""
        wallet = _id(wallet_id, "wallet_id")
        route = "/v1/wallets/{walletId}/owned-cards"
        path = _cursor(f"/v1/wallets/{wallet}/owned-cards", cursor)
        return (
            await self._transport.send(
                _spec(self._transport.core, "GET", route, path), _page_reader(MaskedCard.from_json)
            )
        )[0]

    async def list(self, wallet_id: UUID | str) -> AsyncIterator[MaskedCard]:
        """Yield all masked cards without silently stopping at the first page."""
        cursor = None
        seen: set[str] = set()
        while True:
            page = await self.list_page(wallet_id, cursor)
            for item in page.items:
                yield item
            cursor = _next_cursor(page.next_cursor, seen)
            if not cursor:
                break

    async def get(self, wallet_id: UUID | str, sold_card_id: UUID | str) -> MaskedCard:
        """Read one masked card."""
        wallet, sold = _id(wallet_id, "wallet_id"), _id(sold_card_id, "sold_card_id")
        route = "/v1/wallets/{walletId}/owned-cards/{soldCardId}"
        return (
            await self._transport.send(
                _spec(self._transport.core, "GET", route, f"/v1/wallets/{wallet}/owned-cards/{sold}"),
                MaskedCard.from_json,
            )
        )[0]

    async def reveal(self, wallet_id: UUID | str, sold_card_id: UUID | str) -> RevealedCredential:
        """Reveal one verified credential only after an explicit request."""
        wallet, sold = _id(wallet_id, "wallet_id"), _id(sold_card_id, "sold_card_id")
        route = "/v1/wallets/{walletId}/owned-cards/{soldCardId}/reveal"
        return (
            await self._transport.send(
                _spec(self._transport.core, "POST", route, f"/v1/wallets/{wallet}/owned-cards/{sold}/reveal"),
                RevealedCredential.from_json,
            )
        )[0]

    async def reveal_invoice(self, wallet_id: UUID | str, invoice_id: UUID | str) -> RevealedCredentialCollection:
        """Reveal all invoice credentials as one verified all-or-none result."""
        wallet, invoice = _id(wallet_id, "wallet_id"), _id(invoice_id, "invoice_id")
        route = "/v1/wallets/{walletId}/invoices/{invoiceId}/owned-cards/reveal"
        return (
            await self._transport.send(
                _spec(
                    self._transport.core, "POST", route, f"/v1/wallets/{wallet}/invoices/{invoice}/owned-cards/reveal"
                ),
                RevealedCredentialCollection.from_json,
            )
        )[0]


class AsyncDiagnosticsOperations:
    """Expose the verified signature self-check without adding an order or other side effect."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def check_signature(self) -> SignatureDiagnostic:
        """Send exactly `{}` because the diagnostic route declares a body and binds its digest."""
        route = "/v1/diagnostics/signature"
        return (
            await self._transport.send(
                _spec(self._transport.core, "POST", route, route, {}), SignatureDiagnostic.from_json
            )
        )[0]


class AsyncOrderOperations:
    """Create and recover purchases without converting missing answers into final refusals."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def create(
        self, *, wallet_id: UUID | str, operation_id: UUID | str, order: CreateOrderRequest
    ) -> OrderResult:
        """Submit a validated order under the operation id already persisted by the caller."""
        return await self._send(wallet_id, operation_id, order, False)

    async def resume(
        self, *, wallet_id: UUID | str, operation_id: UUID | str, order: CreateOrderRequest
    ) -> OrderResult:
        """Repeat the same signed order intent and id to resolve an unknown earlier answer."""
        return await self._send(wallet_id, operation_id, order, True)

    async def get(self, operation_id: UUID | str) -> Order:
        """Read order state only; a GET does not drive recovery or return credentials."""
        identifier = _id(operation_id, "operation_id")
        route = "/v1/orders/{operationId}"
        return (
            await self._transport.send(
                _spec(self._transport.core, "GET", route, f"/v1/orders/{identifier}"), Order.from_json
            )
        )[0]

    async def _send(
        self, wallet_id: UUID | str, operation_id: UUID | str, order: CreateOrderRequest, resuming: bool
    ) -> OrderResult:
        wallet, operation = _id(wallet_id, "wallet_id"), _id(operation_id, "operation_id")
        if order is None:
            raise TypeError("order cannot be None.")
        validate_order(order)
        route = "/v1/wallets/{walletId}/orders"
        spec = _spec(self._transport.core, "POST", route, f"/v1/wallets/{wallet}/orders", order, operation)
        reason: str | None = None
        try:
            model, response, _ = await self._transport.send(spec, Order.from_json)
            outcome = classify_order(model, response)
        except AnisApiError as exc:
            outcome = classify_refusal(exc, operation, resuming)
        except RequestSigningError:
            raise
        except asyncio.CancelledError:
            record_unknown_order(self._transport.core, str(operation), "canceled")
            raise
        except KeyDocumentUnavailableError as exc:
            outcome = OrderOutcomeUnknown(operation, timedelta(seconds=5), exc)
            reason = exc.error_type
        except Exception as exc:
            outcome = OrderOutcomeUnknown(operation, timedelta(seconds=5), exc)
            if isinstance(exc, UnverifiableResponseError):
                reason = "unverifiable"
            elif isinstance(exc, (httpx.TimeoutException, TimeoutError)):
                reason = "timeout"
            elif isinstance(exc, httpx.TransportError):
                reason = "connection"
            else:
                reason = "other"
        record_order_outcome(self._transport.core, outcome, str(operation), reason)
        return outcome


def _query_path(path: str, values: dict[str, object]) -> str:
    """Encode each raw query value exactly once, preserving opaque cursor text."""
    query = urlencode(
        {key: str(value) for key, value in values.items() if value is not None}, quote_via=quote, safe="-_.~"
    )
    return path + ("?" + query if query else "")


class SyncMeterChargeOperations:
    """Create and recover the saved purchase intent under the original operation id."""

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def get_meter_packages_page(self, wallet_id: UUID | str, cursor: str | None = None) -> Page[MeterPackage]:
        """Read one page without replaying purchases or verifying unsigned answers."""
        wallet = _id(wallet_id, "wallet_id")
        route = "/v1/wallets/{walletId}/meter-packages"
        path = _query_path(f"/v1/wallets/{wallet}/meter-packages", {"cursor": cursor})
        return (
            self._transport.send(_spec(self._transport.core, "GET", route, path), _page_reader(MeterPackage.from_json))
        )[0]

    def get_meter_packages(self, wallet_id: UUID | str) -> Iterator[MeterPackage]:
        """Follow every cursor while retaining filters and refusing a repeated continuation."""
        cursor = None
        seen: set[str] = set()
        while True:
            page = self.get_meter_packages_page(wallet_id, cursor)
            yield from page.items
            cursor = _next_cursor(page.next_cursor, seen)
            if cursor is None:
                return

    def get_meter_charges_page(
        self, wallet_id: UUID | str, query: MeterChargesQuery | None = None
    ) -> Page[MeterChargeSummary]:
        """Read one page without replaying purchases or verifying unsigned answers."""
        wallet = _id(wallet_id, "wallet_id")
        route = "/v1/wallets/{walletId}/meter-charges"
        path = _query_path(f"/v1/wallets/{wallet}/meter-charges", query.to_json() if query is not None else {})
        return (
            self._transport.send(
                _spec(self._transport.core, "GET", route, path), _page_reader(MeterChargeSummary.from_json)
            )
        )[0]

    def get_meter_charges(
        self, wallet_id: UUID | str, query: MeterChargesQuery | None = None
    ) -> Iterator[MeterChargeSummary]:
        """Follow every cursor while retaining filters and refusing a repeated continuation."""
        current = query or MeterChargesQuery()
        seen: set[str] = {current.cursor} if current.cursor is not None else set()
        while True:
            page = self.get_meter_charges_page(wallet_id, current)
            yield from page.items
            cursor = _next_cursor(page.next_cursor, seen)
            if cursor is None:
                return
            current = replace(current, cursor=cursor)

    def create(
        self, *, wallet_id: UUID | str, operation_id: UUID | str, request: CreateMeterChargeRequest
    ) -> MeterChargeResult:
        """Send the caller-persisted id and unchanged intent with fresh signing material."""
        return self._send(wallet_id, operation_id, request, False)

    def resume(
        self, *, wallet_id: UUID | str, operation_id: UUID | str, request: CreateMeterChargeRequest
    ) -> MeterChargeResult:
        """Send the caller-persisted id and unchanged intent with fresh signing material."""
        return self._send(wallet_id, operation_id, request, True)

    def get(self, operation_id: UUID | str) -> MeterCharge | MeterChargeAccepted:
        """Read signed state, preserving a processing acceptance before owner projection."""
        operation = _id(operation_id, "operation_id")
        route = "/v1/meter-charges/{operationId}"
        data, response, _ = self._transport.send(
            _spec(self._transport.core, "GET", route, f"/v1/meter-charges/{operation}"), object_data
        )
        return read_meter_charge(data, response, operation)

    def _send(
        self, wallet_id: UUID | str, operation_id: UUID | str, request: CreateMeterChargeRequest, resuming: bool
    ) -> MeterChargeResult:
        wallet, operation = _id(wallet_id, "wallet_id"), _id(operation_id, "operation_id")
        if request is None:
            raise TypeError("request cannot be None.")
        route = "/v1/wallets/{walletId}/meter-charges"
        spec = _spec(self._transport.core, "POST", route, f"/v1/wallets/{wallet}/meter-charges", request, operation)
        try:
            data, response, _ = self._transport.send(spec, object_data)
            model = read_meter_charge(data, response, operation)
            return classify_meter_charge(model, response)
        except AnisApiError as exc:
            if product_refusal_is_final(exc, resuming, meter=True):
                return MeterChargeNotPlaced(operation, exc)
            return MeterChargeOutcomeUnknown(operation, product_refusal_delay(exc), exc)
        except RequestSigningError:
            raise
        except Exception as exc:
            return MeterChargeOutcomeUnknown(operation, timedelta(seconds=5), exc)


class SyncDirectRechargeOperations:
    """Create and recover the saved purchase intent under the original operation id."""

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def get_direct_recharges_page(
        self, wallet_id: UUID | str, query: DirectRechargesQuery | None = None
    ) -> Page[DirectRechargeSummary]:
        """Read one page without replaying purchases or verifying unsigned answers."""
        wallet = _id(wallet_id, "wallet_id")
        route = "/v1/wallets/{walletId}/direct-recharges"
        path = _query_path(f"/v1/wallets/{wallet}/direct-recharges", query.to_json() if query is not None else {})
        return (
            self._transport.send(
                _spec(self._transport.core, "GET", route, path), _page_reader(DirectRechargeSummary.from_json)
            )
        )[0]

    def get_direct_recharges(
        self, wallet_id: UUID | str, query: DirectRechargesQuery | None = None
    ) -> Iterator[DirectRechargeSummary]:
        """Follow every cursor while retaining filters and refusing a repeated continuation."""
        current = query or DirectRechargesQuery()
        seen: set[str] = {current.cursor} if current.cursor is not None else set()
        while True:
            page = self.get_direct_recharges_page(wallet_id, current)
            yield from page.items
            cursor = _next_cursor(page.next_cursor, seen)
            if cursor is None:
                return
            current = replace(current, cursor=cursor)

    def create(
        self, *, wallet_id: UUID | str, operation_id: UUID | str, request: CreateDirectRechargeRequest
    ) -> DirectRechargeResult:
        """Send the caller-persisted id and unchanged intent with fresh signing material."""
        return self._send(wallet_id, operation_id, request, False)

    def resume(
        self, *, wallet_id: UUID | str, operation_id: UUID | str, request: CreateDirectRechargeRequest
    ) -> DirectRechargeResult:
        """Send the caller-persisted id and unchanged intent with fresh signing material."""
        return self._send(wallet_id, operation_id, request, True)

    def get(self, operation_id: UUID | str) -> DirectRecharge | DirectRechargeAccepted:
        """Read signed state, preserving a processing acceptance before owner projection."""
        operation = _id(operation_id, "operation_id")
        route = "/v1/direct-recharges/{operationId}"
        data, response, _ = self._transport.send(
            _spec(self._transport.core, "GET", route, f"/v1/direct-recharges/{operation}"), object_data
        )
        return read_direct_recharge(data, response, operation)

    def _send(
        self, wallet_id: UUID | str, operation_id: UUID | str, request: CreateDirectRechargeRequest, resuming: bool
    ) -> DirectRechargeResult:
        wallet, operation = _id(wallet_id, "wallet_id"), _id(operation_id, "operation_id")
        if request is None:
            raise TypeError("request cannot be None.")
        route = "/v1/wallets/{walletId}/direct-recharges"
        spec = _spec(self._transport.core, "POST", route, f"/v1/wallets/{wallet}/direct-recharges", request, operation)
        try:
            data, response, _ = self._transport.send(spec, object_data)
            model = read_direct_recharge(data, response, operation)
            return classify_direct_recharge(model, response)
        except AnisApiError as exc:
            if product_refusal_is_final(exc, resuming, meter=False):
                return DirectRechargeNotPlaced(operation, exc)
            return DirectRechargeOutcomeUnknown(operation, product_refusal_delay(exc), exc)
        except RequestSigningError:
            raise
        except Exception as exc:
            return DirectRechargeOutcomeUnknown(operation, timedelta(seconds=5), exc)

    def update_recipient(
        self, operation_id: UUID | str, request: UpdateDirectRechargeRecipientRequest
    ) -> DirectRechargeProcessing:
        """Sign the exact recipient bytes once without a purchase key or recovery replay."""
        operation = _id(operation_id, "operation_id")
        route = "/v1/direct-recharges/{operationId}/recipient"
        data, response, _ = self._transport.send(
            _spec(self._transport.core, "PATCH", route, f"/v1/direct-recharges/{operation}/recipient", request),
            object_data,
        )
        return read_recipient_update(data, response, operation)


class SyncDirectRechargeProductOperations:
    """Read wallet-priced products, dynamic recipient fields, locations and quotes."""

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def get_direct_recharge_products_page(
        self, wallet_id: UUID | str, query: DirectRechargeProductsQuery | None = None
    ) -> Page[DirectRechargeProductSummary]:
        """Read one page without replaying purchases or verifying unsigned answers."""
        wallet = _id(wallet_id, "wallet_id")
        route = "/v1/wallets/{walletId}/direct-recharge-products"
        path = _query_path(
            f"/v1/wallets/{wallet}/direct-recharge-products", query.to_json() if query is not None else {}
        )
        return (
            self._transport.send(
                _spec(self._transport.core, "GET", route, path), _page_reader(DirectRechargeProductSummary.from_json)
            )
        )[0]

    def get_direct_recharge_products(
        self, wallet_id: UUID | str, query: DirectRechargeProductsQuery | None = None
    ) -> Iterator[DirectRechargeProductSummary]:
        """Follow every cursor while retaining filters and refusing a repeated continuation."""
        current = query or DirectRechargeProductsQuery()
        seen: set[str] = {current.cursor} if current.cursor is not None else set()
        while True:
            page = self.get_direct_recharge_products_page(wallet_id, current)
            yield from page.items
            cursor = _next_cursor(page.next_cursor, seen)
            if cursor is None:
                return
            current = replace(current, cursor=cursor)

    def get(self, wallet_id: UUID | str, product_id: UUID | str) -> DirectRechargeProduct:
        """Read the dynamic fields for this wallet's selected product."""
        wallet, product = _id(wallet_id, "wallet_id"), _id(product_id, "product_id")
        route = "/v1/wallets/{walletId}/direct-recharge-products/{productId}"
        return (
            self._transport.send(
                _spec(self._transport.core, "GET", route, f"/v1/wallets/{wallet}/direct-recharge-products/{product}"),
                DirectRechargeProduct.from_json,
            )
        )[0]

    def get_direct_recharge_product_locations_page(
        self, wallet_id: UUID | str, product_id: UUID | str, query: DirectRechargeLocationsQuery | None = None
    ) -> Page[DirectRechargeLocation]:
        """Read one page without replaying purchases or verifying unsigned answers."""
        wallet = _id(wallet_id, "wallet_id")
        product = _id(product_id, "product_id")
        route = "/v1/wallets/{walletId}/direct-recharge-products/{productId}/locations"
        path = _query_path(
            f"/v1/wallets/{wallet}/direct-recharge-products/{product}/locations",
            query.to_json() if query is not None else {},
        )
        return (
            self._transport.send(
                _spec(self._transport.core, "GET", route, path), _page_reader(DirectRechargeLocation.from_json)
            )
        )[0]

    def get_direct_recharge_product_locations(
        self, wallet_id: UUID | str, product_id: UUID | str, query: DirectRechargeLocationsQuery | None = None
    ) -> Iterator[DirectRechargeLocation]:
        """Follow every cursor while retaining filters and refusing a repeated continuation."""
        current = query or DirectRechargeLocationsQuery()
        seen: set[str] = {current.cursor} if current.cursor is not None else set()
        while True:
            page = self.get_direct_recharge_product_locations_page(wallet_id, product_id, current)
            yield from page.items
            cursor = _next_cursor(page.next_cursor, seen)
            if cursor is None:
                return
            current = replace(current, cursor=cursor)

    def quote(
        self, wallet_id: UUID | str, product_id: UUID | str, amount: str, amount_in: DirectRechargeAmountIn
    ) -> DirectRechargeQuote:
        """Quote exact decimal text in LYD or the product's payout currency."""
        wallet, product = _id(wallet_id, "wallet_id"), _id(product_id, "product_id")
        if amount_in not in {DirectRechargeAmountIn.LYD, DirectRechargeAmountIn.FX}:
            raise ValueError("amount_in must be lyd or fx.")
        if not isinstance(amount, str):
            raise TypeError("amount must be decimal text.")
        route = "/v1/wallets/{walletId}/direct-recharge-products/{productId}/quote"
        path = _query_path(
            f"/v1/wallets/{wallet}/direct-recharge-products/{product}/quote", {"amount": amount, "amountIn": amount_in}
        )
        return (self._transport.send(_spec(self._transport.core, "GET", route, path), DirectRechargeQuote.from_json))[0]


class SyncWebhookEndpointOperations:
    """Manage the admitted application endpoint without a product scope or purchase recovery."""

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def get(self) -> WebhookEndpoint:
        """Send once under the route's fixed signing and answer policy."""
        route = "/v1/webhook-endpoint"
        return (
            self._transport.send(_spec(self._transport.core, "GET", route, route, None), WebhookEndpoint.from_json)
        )[0]

    def set(self, request: SetWebhookEndpointRequest) -> WebhookEndpoint:
        """Send once under the route's fixed signing and answer policy."""
        route = "/v1/webhook-endpoint"
        return (
            self._transport.send(_spec(self._transport.core, "PUT", route, route, request), WebhookEndpoint.from_json)
        )[0]

    def test(self) -> WebhookEventAccepted:
        """Send once under the route's fixed signing and answer policy."""
        route = "/v1/webhook-endpoint/test"
        return (
            self._transport.send(_spec(self._transport.core, "POST", route, route, {}), WebhookEventAccepted.from_json)
        )[0]


class SyncWebhookEventOperations:
    """Read delivery summaries and explicitly request another delivery of an existing event."""

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def get_webhook_events_page(self, query: WebhookEventsQuery | None = None) -> Page[WebhookEvent]:
        """Read one page without replaying purchases or verifying unsigned answers."""
        route = "/v1/webhook-events"
        path = _query_path("/v1/webhook-events", query.to_json() if query is not None else {})
        return (
            self._transport.send(_spec(self._transport.core, "GET", route, path), _page_reader(WebhookEvent.from_json))
        )[0]

    def get_webhook_events(self, query: WebhookEventsQuery | None = None) -> Iterator[WebhookEvent]:
        """Follow every cursor while retaining filters and refusing a repeated continuation."""
        current = query or WebhookEventsQuery()
        seen: set[str] = {current.cursor} if current.cursor is not None else set()
        while True:
            page = self.get_webhook_events_page(current)
            yield from page.items
            cursor = _next_cursor(page.next_cursor, seen)
            if cursor is None:
                return
            current = replace(current, cursor=cursor)

    def redeliver(self, event_id: UUID | str) -> WebhookEventAccepted:
        """Request redelivery once with nonce signing and no Idempotency-Key."""
        event = _id(event_id, "event_id")
        route = "/v1/webhook-events/{eventId}/redeliver"
        return (
            self._transport.send(
                _spec(self._transport.core, "POST", route, f"/v1/webhook-events/{event}/redeliver", {}),
                WebhookEventAccepted.from_json,
            )
        )[0]


class AsyncMeterChargeOperations:
    """Create and recover the saved purchase intent under the original operation id."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def get_meter_packages_page(self, wallet_id: UUID | str, cursor: str | None = None) -> Page[MeterPackage]:
        """Read one page without replaying purchases or verifying unsigned answers."""
        wallet = _id(wallet_id, "wallet_id")
        route = "/v1/wallets/{walletId}/meter-packages"
        path = _query_path(f"/v1/wallets/{wallet}/meter-packages", {"cursor": cursor})
        return (
            await self._transport.send(
                _spec(self._transport.core, "GET", route, path), _page_reader(MeterPackage.from_json)
            )
        )[0]

    async def get_meter_packages(self, wallet_id: UUID | str) -> AsyncIterator[MeterPackage]:
        """Follow every cursor while retaining filters and refusing a repeated continuation."""
        cursor = None
        seen: set[str] = set()
        while True:
            page = await self.get_meter_packages_page(wallet_id, cursor)
            for item in page.items:
                yield item
            cursor = _next_cursor(page.next_cursor, seen)
            if cursor is None:
                return

    async def get_meter_charges_page(
        self, wallet_id: UUID | str, query: MeterChargesQuery | None = None
    ) -> Page[MeterChargeSummary]:
        """Read one page without replaying purchases or verifying unsigned answers."""
        wallet = _id(wallet_id, "wallet_id")
        route = "/v1/wallets/{walletId}/meter-charges"
        path = _query_path(f"/v1/wallets/{wallet}/meter-charges", query.to_json() if query is not None else {})
        return (
            await self._transport.send(
                _spec(self._transport.core, "GET", route, path), _page_reader(MeterChargeSummary.from_json)
            )
        )[0]

    async def get_meter_charges(
        self, wallet_id: UUID | str, query: MeterChargesQuery | None = None
    ) -> AsyncIterator[MeterChargeSummary]:
        """Follow every cursor while retaining filters and refusing a repeated continuation."""
        current = query or MeterChargesQuery()
        seen: set[str] = {current.cursor} if current.cursor is not None else set()
        while True:
            page = await self.get_meter_charges_page(wallet_id, current)
            for item in page.items:
                yield item
            cursor = _next_cursor(page.next_cursor, seen)
            if cursor is None:
                return
            current = replace(current, cursor=cursor)

    async def create(
        self, *, wallet_id: UUID | str, operation_id: UUID | str, request: CreateMeterChargeRequest
    ) -> MeterChargeResult:
        """Send the caller-persisted id and unchanged intent with fresh signing material."""
        return await self._send(wallet_id, operation_id, request, False)

    async def resume(
        self, *, wallet_id: UUID | str, operation_id: UUID | str, request: CreateMeterChargeRequest
    ) -> MeterChargeResult:
        """Send the caller-persisted id and unchanged intent with fresh signing material."""
        return await self._send(wallet_id, operation_id, request, True)

    async def get(self, operation_id: UUID | str) -> MeterCharge | MeterChargeAccepted:
        """Read signed state, preserving a processing acceptance before owner projection."""
        operation = _id(operation_id, "operation_id")
        route = "/v1/meter-charges/{operationId}"
        data, response, _ = await self._transport.send(
            _spec(self._transport.core, "GET", route, f"/v1/meter-charges/{operation}"), object_data
        )
        return read_meter_charge(data, response, operation)

    async def _send(
        self, wallet_id: UUID | str, operation_id: UUID | str, request: CreateMeterChargeRequest, resuming: bool
    ) -> MeterChargeResult:
        wallet, operation = _id(wallet_id, "wallet_id"), _id(operation_id, "operation_id")
        if request is None:
            raise TypeError("request cannot be None.")
        route = "/v1/wallets/{walletId}/meter-charges"
        spec = _spec(self._transport.core, "POST", route, f"/v1/wallets/{wallet}/meter-charges", request, operation)
        try:
            data, response, _ = await self._transport.send(spec, object_data)
            model = read_meter_charge(data, response, operation)
            return classify_meter_charge(model, response)
        except AnisApiError as exc:
            if product_refusal_is_final(exc, resuming, meter=True):
                return MeterChargeNotPlaced(operation, exc)
            return MeterChargeOutcomeUnknown(operation, product_refusal_delay(exc), exc)
        except RequestSigningError:
            raise
        except Exception as exc:
            return MeterChargeOutcomeUnknown(operation, timedelta(seconds=5), exc)


class AsyncDirectRechargeOperations:
    """Create and recover the saved purchase intent under the original operation id."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def get_direct_recharges_page(
        self, wallet_id: UUID | str, query: DirectRechargesQuery | None = None
    ) -> Page[DirectRechargeSummary]:
        """Read one page without replaying purchases or verifying unsigned answers."""
        wallet = _id(wallet_id, "wallet_id")
        route = "/v1/wallets/{walletId}/direct-recharges"
        path = _query_path(f"/v1/wallets/{wallet}/direct-recharges", query.to_json() if query is not None else {})
        return (
            await self._transport.send(
                _spec(self._transport.core, "GET", route, path), _page_reader(DirectRechargeSummary.from_json)
            )
        )[0]

    async def get_direct_recharges(
        self, wallet_id: UUID | str, query: DirectRechargesQuery | None = None
    ) -> AsyncIterator[DirectRechargeSummary]:
        """Follow every cursor while retaining filters and refusing a repeated continuation."""
        current = query or DirectRechargesQuery()
        seen: set[str] = {current.cursor} if current.cursor is not None else set()
        while True:
            page = await self.get_direct_recharges_page(wallet_id, current)
            for item in page.items:
                yield item
            cursor = _next_cursor(page.next_cursor, seen)
            if cursor is None:
                return
            current = replace(current, cursor=cursor)

    async def create(
        self, *, wallet_id: UUID | str, operation_id: UUID | str, request: CreateDirectRechargeRequest
    ) -> DirectRechargeResult:
        """Send the caller-persisted id and unchanged intent with fresh signing material."""
        return await self._send(wallet_id, operation_id, request, False)

    async def resume(
        self, *, wallet_id: UUID | str, operation_id: UUID | str, request: CreateDirectRechargeRequest
    ) -> DirectRechargeResult:
        """Send the caller-persisted id and unchanged intent with fresh signing material."""
        return await self._send(wallet_id, operation_id, request, True)

    async def get(self, operation_id: UUID | str) -> DirectRecharge | DirectRechargeAccepted:
        """Read signed state, preserving a processing acceptance before owner projection."""
        operation = _id(operation_id, "operation_id")
        route = "/v1/direct-recharges/{operationId}"
        data, response, _ = await self._transport.send(
            _spec(self._transport.core, "GET", route, f"/v1/direct-recharges/{operation}"), object_data
        )
        return read_direct_recharge(data, response, operation)

    async def _send(
        self, wallet_id: UUID | str, operation_id: UUID | str, request: CreateDirectRechargeRequest, resuming: bool
    ) -> DirectRechargeResult:
        wallet, operation = _id(wallet_id, "wallet_id"), _id(operation_id, "operation_id")
        if request is None:
            raise TypeError("request cannot be None.")
        route = "/v1/wallets/{walletId}/direct-recharges"
        spec = _spec(self._transport.core, "POST", route, f"/v1/wallets/{wallet}/direct-recharges", request, operation)
        try:
            data, response, _ = await self._transport.send(spec, object_data)
            model = read_direct_recharge(data, response, operation)
            return classify_direct_recharge(model, response)
        except AnisApiError as exc:
            if product_refusal_is_final(exc, resuming, meter=False):
                return DirectRechargeNotPlaced(operation, exc)
            return DirectRechargeOutcomeUnknown(operation, product_refusal_delay(exc), exc)
        except RequestSigningError:
            raise
        except Exception as exc:
            return DirectRechargeOutcomeUnknown(operation, timedelta(seconds=5), exc)

    async def update_recipient(
        self, operation_id: UUID | str, request: UpdateDirectRechargeRecipientRequest
    ) -> DirectRechargeProcessing:
        """Sign the exact recipient bytes once without a purchase key or recovery replay."""
        operation = _id(operation_id, "operation_id")
        route = "/v1/direct-recharges/{operationId}/recipient"
        data, response, _ = await self._transport.send(
            _spec(self._transport.core, "PATCH", route, f"/v1/direct-recharges/{operation}/recipient", request),
            object_data,
        )
        return read_recipient_update(data, response, operation)


class AsyncDirectRechargeProductOperations:
    """Read wallet-priced products, dynamic recipient fields, locations and quotes."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def get_direct_recharge_products_page(
        self, wallet_id: UUID | str, query: DirectRechargeProductsQuery | None = None
    ) -> Page[DirectRechargeProductSummary]:
        """Read one page without replaying purchases or verifying unsigned answers."""
        wallet = _id(wallet_id, "wallet_id")
        route = "/v1/wallets/{walletId}/direct-recharge-products"
        path = _query_path(
            f"/v1/wallets/{wallet}/direct-recharge-products", query.to_json() if query is not None else {}
        )
        return (
            await self._transport.send(
                _spec(self._transport.core, "GET", route, path), _page_reader(DirectRechargeProductSummary.from_json)
            )
        )[0]

    async def get_direct_recharge_products(
        self, wallet_id: UUID | str, query: DirectRechargeProductsQuery | None = None
    ) -> AsyncIterator[DirectRechargeProductSummary]:
        """Follow every cursor while retaining filters and refusing a repeated continuation."""
        current = query or DirectRechargeProductsQuery()
        seen: set[str] = {current.cursor} if current.cursor is not None else set()
        while True:
            page = await self.get_direct_recharge_products_page(wallet_id, current)
            for item in page.items:
                yield item
            cursor = _next_cursor(page.next_cursor, seen)
            if cursor is None:
                return
            current = replace(current, cursor=cursor)

    async def get(self, wallet_id: UUID | str, product_id: UUID | str) -> DirectRechargeProduct:
        """Read the dynamic fields for this wallet's selected product."""
        wallet, product = _id(wallet_id, "wallet_id"), _id(product_id, "product_id")
        route = "/v1/wallets/{walletId}/direct-recharge-products/{productId}"
        return (
            await self._transport.send(
                _spec(self._transport.core, "GET", route, f"/v1/wallets/{wallet}/direct-recharge-products/{product}"),
                DirectRechargeProduct.from_json,
            )
        )[0]

    async def get_direct_recharge_product_locations_page(
        self, wallet_id: UUID | str, product_id: UUID | str, query: DirectRechargeLocationsQuery | None = None
    ) -> Page[DirectRechargeLocation]:
        """Read one page without replaying purchases or verifying unsigned answers."""
        wallet = _id(wallet_id, "wallet_id")
        product = _id(product_id, "product_id")
        route = "/v1/wallets/{walletId}/direct-recharge-products/{productId}/locations"
        path = _query_path(
            f"/v1/wallets/{wallet}/direct-recharge-products/{product}/locations",
            query.to_json() if query is not None else {},
        )
        return (
            await self._transport.send(
                _spec(self._transport.core, "GET", route, path), _page_reader(DirectRechargeLocation.from_json)
            )
        )[0]

    async def get_direct_recharge_product_locations(
        self, wallet_id: UUID | str, product_id: UUID | str, query: DirectRechargeLocationsQuery | None = None
    ) -> AsyncIterator[DirectRechargeLocation]:
        """Follow every cursor while retaining filters and refusing a repeated continuation."""
        current = query or DirectRechargeLocationsQuery()
        seen: set[str] = {current.cursor} if current.cursor is not None else set()
        while True:
            page = await self.get_direct_recharge_product_locations_page(wallet_id, product_id, current)
            for item in page.items:
                yield item
            cursor = _next_cursor(page.next_cursor, seen)
            if cursor is None:
                return
            current = replace(current, cursor=cursor)

    async def quote(
        self, wallet_id: UUID | str, product_id: UUID | str, amount: str, amount_in: DirectRechargeAmountIn
    ) -> DirectRechargeQuote:
        """Quote exact decimal text in LYD or the product's payout currency."""
        wallet, product = _id(wallet_id, "wallet_id"), _id(product_id, "product_id")
        if amount_in not in {DirectRechargeAmountIn.LYD, DirectRechargeAmountIn.FX}:
            raise ValueError("amount_in must be lyd or fx.")
        if not isinstance(amount, str):
            raise TypeError("amount must be decimal text.")
        route = "/v1/wallets/{walletId}/direct-recharge-products/{productId}/quote"
        path = _query_path(
            f"/v1/wallets/{wallet}/direct-recharge-products/{product}/quote", {"amount": amount, "amountIn": amount_in}
        )
        return (
            await self._transport.send(_spec(self._transport.core, "GET", route, path), DirectRechargeQuote.from_json)
        )[0]


class AsyncWebhookEndpointOperations:
    """Manage the admitted application endpoint without a product scope or purchase recovery."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def get(self) -> WebhookEndpoint:
        """Send once under the route's fixed signing and answer policy."""
        route = "/v1/webhook-endpoint"
        return (
            await self._transport.send(
                _spec(self._transport.core, "GET", route, route, None), WebhookEndpoint.from_json
            )
        )[0]

    async def set(self, request: SetWebhookEndpointRequest) -> WebhookEndpoint:
        """Send once under the route's fixed signing and answer policy."""
        route = "/v1/webhook-endpoint"
        return (
            await self._transport.send(
                _spec(self._transport.core, "PUT", route, route, request), WebhookEndpoint.from_json
            )
        )[0]

    async def test(self) -> WebhookEventAccepted:
        """Send once under the route's fixed signing and answer policy."""
        route = "/v1/webhook-endpoint/test"
        return (
            await self._transport.send(
                _spec(self._transport.core, "POST", route, route, {}), WebhookEventAccepted.from_json
            )
        )[0]


class AsyncWebhookEventOperations:
    """Read delivery summaries and explicitly request another delivery of an existing event."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def get_webhook_events_page(self, query: WebhookEventsQuery | None = None) -> Page[WebhookEvent]:
        """Read one page without replaying purchases or verifying unsigned answers."""
        route = "/v1/webhook-events"
        path = _query_path("/v1/webhook-events", query.to_json() if query is not None else {})
        return (
            await self._transport.send(
                _spec(self._transport.core, "GET", route, path), _page_reader(WebhookEvent.from_json)
            )
        )[0]

    async def get_webhook_events(self, query: WebhookEventsQuery | None = None) -> AsyncIterator[WebhookEvent]:
        """Follow every cursor while retaining filters and refusing a repeated continuation."""
        current = query or WebhookEventsQuery()
        seen: set[str] = {current.cursor} if current.cursor is not None else set()
        while True:
            page = await self.get_webhook_events_page(current)
            for item in page.items:
                yield item
            cursor = _next_cursor(page.next_cursor, seen)
            if cursor is None:
                return
            current = replace(current, cursor=cursor)

    async def redeliver(self, event_id: UUID | str) -> WebhookEventAccepted:
        """Request redelivery once with nonce signing and no Idempotency-Key."""
        event = _id(event_id, "event_id")
        route = "/v1/webhook-events/{eventId}/redeliver"
        return (
            await self._transport.send(
                _spec(self._transport.core, "POST", route, f"/v1/webhook-events/{event}/redeliver", {}),
                WebhookEventAccepted.from_json,
            )
        )[0]
