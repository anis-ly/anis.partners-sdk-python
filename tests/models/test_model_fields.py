"""Optional wire additions remain optional and keep their contract camelCase names."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from anis_partners.models import (
    CatalogueCard,
    CatalogueCategory,
    CatalogueCategoryType,
    CatalogueSubcategory,
    MaskedCard,
    Money,
    Order,
    OrderStatus,
    RevealedCredential,
)


def test_subcategory_reads_its_disclaimer() -> None:
    """Keep owner redemption terms available to show before purchase."""
    subcategory = CatalogueSubcategory.from_json(
        '{"id":"7a1c3e5f-2b4d-4f68-8a0c-9e1b3d5f7a2c","disclaimer":{"ar":"ملاحظة","en":"Valid in Libya only."}}'
    )
    assert subcategory.disclaimer is not None
    assert subcategory.disclaimer.en == "Valid in Libya only."
    assert subcategory.disclaimer.ar == "ملاحظة"


def test_subcategory_without_a_disclaimer_has_none() -> None:
    """Do not invent fallback purchase terms when neither translation was supplied."""
    assert CatalogueSubcategory.from_json('{"id":"7a1c3e5f-2b4d-4f68-8a0c-9e1b3d5f7a2c"}').disclaimer is None


def test_catalogue_card_reads_its_quantity_limits() -> None:
    """Expose live card limits before a partner submits an order."""
    card = CatalogueCard.from_json(
        '{"id":"8d4b1e73-9a25-4c60-8f37-6b2e9d5a1c48","minimumQuantity":1,"maximumQuantity":100}'
    )
    assert card.minimum_quantity == 1
    assert card.maximum_quantity == 100


def test_catalogue_card_without_quantity_limits_has_none() -> None:
    """Keep absent limits distinct from a server-published zero limit."""
    card = CatalogueCard.from_json('{"id":"8d4b1e73-9a25-4c60-8f37-6b2e9d5a1c48"}')
    assert card.minimum_quantity is None
    assert card.maximum_quantity is None


def test_order_reads_its_reference_failure_code_and_withheld_flag() -> None:
    """Retain order correlation and withheld-code facts so a paid order is not bought again."""
    order = Order.from_json(
        '{"operationId":"9b2e4f17-3c6a-4d58-b0e1-7a5c8d2f6b34","status":"failed",'
        '"externalReference":"INV-77","failureCode":"out_of_stock","codesWithheld":true}'
    )
    assert order.external_reference == "INV-77"
    assert order.failure_code == "out_of_stock"
    assert order.codes_withheld is True


def test_order_without_the_new_members_leaves_them_none() -> None:
    """Allow earlier API answers to omit new response members without inventing values."""
    order = Order.from_json('{"operationId":"9b2e4f17-3c6a-4d58-b0e1-7a5c8d2f6b34","status":"completed"}')
    assert order.external_reference is None
    assert order.failure_code is None
    assert order.codes_withheld is None


def test_revealed_credential_reads_its_expiry_and_reveal_details() -> None:
    """Keep reveal context attached to the protected credential for support and customer delivery."""
    credential = RevealedCredential.from_json(
        '{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"1234",'
        '"expiryDate":"2027-03-31","invoiceId":"c1a7e2d9-5b64-4f18-9e03-2d7a6c4b8f51",'
        '"card":{"id":"8d4b1e73-9a25-4c60-8f37-6b2e9d5a1c48",'
        '"name":{"ar":"بطاقة","en":"Card"}},"purchasedAt":"2026-09-19T08:00:00Z"}'
    )
    assert credential.expiry_date is not None
    assert credential.expiry_date.isoformat() == "2027-03-31"
    assert credential.invoice_id == UUID("c1a7e2d9-5b64-4f18-9e03-2d7a6c4b8f51")
    assert credential.card is not None
    assert credential.card.id == UUID("8d4b1e73-9a25-4c60-8f37-6b2e9d5a1c48")
    assert credential.card.name is not None
    assert credential.card.name.en == "Card"
    assert credential.purchased_at == datetime(2026, 9, 19, 8, 0, tzinfo=UTC)


def test_revealed_credential_without_the_new_members_leaves_them_none() -> None:
    """Keep absent reveal additions optional for older server responses."""
    credential = RevealedCredential.from_json('{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","voucher":"1234"}')
    assert credential.expiry_date is None
    assert credential.invoice_id is None
    assert credential.card is None
    assert credential.purchased_at is None


def test_masked_card_reads_its_price_expiry_invoice_number_face_value_and_subcategory() -> None:
    """Keep the original charged price and masked details available without exposing the voucher."""
    card = MaskedCard.from_json(
        '{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","credentialAvailable":false,'
        '"unitPrice":{"amount":"10.500","currency":"LYD"},"expiryDate":"2027-03-31",'
        '"invoiceNumber":1042,"card":{"id":"8d4b1e73-9a25-4c60-8f37-6b2e9d5a1c48","faceValue":"10 USD",'
        '"subcategory":{"id":"7a1c3e5f-2b4d-4f68-8a0c-9e1b3d5f7a2c",'
        '"name":{"ar":"فئة","en":"Games"}}}}'
    )
    assert card.unit_price == Money(Decimal("10.500"), "LYD")
    assert card.expiry_date is not None
    assert card.expiry_date.isoformat() == "2027-03-31"
    assert card.invoice_number == 1042
    assert card.card is not None
    assert card.card.face_value == "10 USD"
    assert card.card.subcategory is not None
    assert card.card.subcategory.id == UUID("7a1c3e5f-2b4d-4f68-8a0c-9e1b3d5f7a2c")
    assert card.card.subcategory.name is not None
    assert card.card.subcategory.name.en == "Games"
    assert card.credential_available is False


def test_masked_card_without_the_new_members_leaves_them_none() -> None:
    """Allow old masked projections to omit price and descriptive additions."""
    card = MaskedCard.from_json('{"soldCardId":"4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046","credentialAvailable":true}')
    assert card.unit_price is None
    assert card.expiry_date is None
    assert card.invoice_number is None
    assert card.card is None


def test_unknown_catalogue_and_order_enums_map_to_unknown() -> None:
    """Keep reading a response when a future server enum value is not known by this SDK version."""
    category = CatalogueCategory.from_json('{"id":"00000000-0000-0000-0000-000000000001","type":"regional"}')
    order = Order.from_json('{"operationId":"00000000-0000-0000-0000-000000000001","status":"recovering"}')
    assert category.type is CatalogueCategoryType.UNKNOWN
    assert order.status is OrderStatus.UNKNOWN


def test_card_summary_round_trips_in_masked_revealed_and_order_answers() -> None:
    """Keep the same complete display object attached to every sold credential representation."""
    from anis_partners import CardSummary

    summary = {
        "id": "8d4b1e73-9a25-4c60-8f37-6b2e9d5a1c48",
        "name": {"ar": "بطاقة", "en": "Card"},
        "faceValue": "10 USD",
        "logo": "https://assets.anis.ly/card.png",
        "subcategory": {"id": "7a1c3e5f-2b4d-4f68-8a0c-9e1b3d5f7a2c", "name": {"en": "Games"}},
        "category": {"id": "00000000-0000-0000-0000-000000000001", "name": {"en": "Digital"}},
    }
    masked_json = {
        "soldCardId": "4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046",
        "operationId": "9b2e4f17-3c6a-4d58-b0e1-7a5c8d2f6b34",
        "invoiceId": "c1a7e2d9-5b64-4f18-9e03-2d7a6c4b8f51",
        "invoiceNumber": 1042,
        "card": summary,
        "serialNumberMasked": "***1234",
        "credentialAvailable": True,
        "purchasedAt": "2026-10-11T09:00:00Z",
        "unitPrice": {"amount": "10.500", "currency": "LYD"},
        "expiryDate": "2027-03-31",
    }
    masked = MaskedCard.from_json(masked_json)
    assert masked.to_json() == masked_json
    assert masked.sold_card_id == UUID("4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046")
    assert isinstance(masked.card, CardSummary)
    assert not hasattr(masked, "id")
    assert not hasattr(masked, "order_operation_id")
    assert not hasattr(masked, "face_value")
    revealed_json = {
        "soldCardId": masked_json["soldCardId"],
        "serialNumber": "1234",
        "voucher": "5678",
        "revealedAt": "2026-10-11T09:05:00Z",
        "expiryDate": "2027-03-31",
        "invoiceId": masked_json["invoiceId"],
        "card": summary,
        "purchasedAt": masked_json["purchasedAt"],
    }
    revealed = RevealedCredential.from_json(revealed_json)
    assert revealed.card == masked.card
    assert revealed.to_json() == revealed_json
    order = Order.from_json(
        {"operationId": masked_json["operationId"], "status": "completed", "soldCards": [revealed_json]}
    )
    assert order.sold_cards == (revealed,)
    assert order.to_json()["soldCards"] == [revealed_json]


def test_catalogue_card_and_subcategory_list_keep_logo_category_and_description() -> None:
    """Expose shared catalogue display context and purchase guidance on list and single reads."""
    category = {"id": "00000000-0000-0000-0000-000000000001", "name": {"en": "Digital"}}
    card = CatalogueCard.from_json(
        {"logo": "https://assets.anis.ly/card.png", "category": category, "minimumQuantity": 1, "maximumQuantity": 100}
    )
    assert card.logo == "https://assets.anis.ly/card.png"
    assert card.category is not None
    assert card.category.to_json() == category
    assert card.to_json()["category"] == category
    subcategory = CatalogueSubcategory.from_json({"description": {"ar": "وصف", "en": "Description"}})
    assert subcategory.description is not None
    assert subcategory.to_json()["description"] == {"ar": "وصف", "en": "Description"}


def test_empty_copy_is_omitted_and_wallet_currency_belongs_to_balance() -> None:
    """Preserve absent optional text and expose a single authoritative wallet currency."""
    from anis_partners import CardSummary, Wallet

    summary = CardSummary.from_json({"name": {"ar": "", "en": ""}, "faceValue": "", "logo": ""})
    assert set(summary.to_json()) == {"id"}
    wallet = Wallet.from_json(
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "name": "Main",
            "balance": {"amount": "1.000", "currency": "LYD"},
        }
    )
    assert wallet.balance.currency == "LYD"
    assert not hasattr(wallet, "currency")
    assert "currency" not in wallet.to_json()


def test_wallet_in_allowed_debt_reads_its_negative_balance() -> None:
    """A wallet using allowed debt has a balance below zero; reading it must not fail."""
    from anis_partners import Wallet

    wallet = Wallet.from_json(
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "name": "Main",
            "balance": {"amount": "-150.000", "currency": "LYD"},
        }
    )
    assert wallet.balance.to_wire_amount() == "-150.000"
    assert wallet.to_json()["balance"] == {"amount": "-150.000", "currency": "LYD"}
