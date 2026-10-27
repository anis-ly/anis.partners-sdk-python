"""Unsigned wallet-priced product, location and quote operations still sign every request."""

from typing import Any

import httpx
import pytest

from anis_partners import (
    DirectRechargeAmountIn,
    DirectRechargeLocationsQuery,
    DirectRechargeProductsQuery,
    DirectRechargeProductType,
    MalformedResponseError,
)
from tests.operations.test_signed_wire_capture import _wire_signature_verifies
from tests.support.partner import OPERATION, WALLET
from tests.support.products import CURSOR, answer, api_requests, collected, product_client, resolved
from tests.support.sdk_wire import SignedMockWire, WireAnswer

pytestmark = pytest.mark.anyio


def product() -> dict[str, Any]:
    return {
        "id": str(OPERATION),
        "title": "عنوان",
        "type": "external",
        "available": False,
        "payoutCurrency": {"name": "جنيه مصري"},
    }


def quote() -> dict[str, Any]:
    m = {"amount": "237.500", "currency": "LYD"}
    return {
        "productId": str(OPERATION),
        "payout": {"amount": "1500.000", "currency": {"name": "جنيه مصري"}},
        "exchangeRate": "0.155000",
        "price": m,
        "commission": m,
        "total": m,
    }


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_products_filters_detail_and_cursor_pages(mode: str) -> None:
    count = 0

    def respond(request: httpx.Request) -> WireAnswer:
        nonlocal count
        count += 1
        return answer({"items": [product()], "nextCursor": CURSOR if count == 1 else None})

    wire = SignedMockWire(respond)
    async with product_client(mode, wire) as client:
        items = await collected(
            client.direct_recharge_products.get_direct_recharge_products(
                WALLET, DirectRechargeProductsQuery(DirectRechargeProductType.EXTERNAL)
            )
        )
        assert len(items) == 2
        assert items[0].limits is None
        wire.answer = lambda request: answer(
            {
                **product(),
                "recipientFields": [
                    {"key": "recipient_name", "name": {"ar": "الاسم"}, "kind": "note", "for": "sender", "order": 1}
                ],
            }
        )
        read = await resolved(client.direct_recharge_products.get(WALLET, OPERATION))
        assert read.recipient_fields[0].for_.value == "sender"
    sent = api_requests(wire)
    assert sent[0].url.params["type"] == sent[1].url.params["type"] == "external"
    assert sent[1].url.params["cursor"] == CURSOR
    assert wire.key_document_requests == 0
    for request in sent:
        _wire_signature_verifies(request)


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_locations_preserve_arabic_search_and_opaque_cursor(mode: str) -> None:
    count = 0

    def respond(request: httpx.Request) -> WireAnswer:
        nonlocal count
        count += 1
        return answer(
            {"items": [{"id": str(OPERATION), "name": "القاهرة"}], "nextCursor": CURSOR if count == 1 else None}
        )

    wire = SignedMockWire(respond)
    async with product_client(mode, wire) as client:
        items = await collected(
            client.direct_recharge_products.get_direct_recharge_product_locations(
                wallet_id=WALLET, product_id=OPERATION, query=DirectRechargeLocationsQuery("طرابلس +/&")
            )
        )
        assert len(items) == 2
    sent = api_requests(wire)
    assert sent[1].url.params["cursor"] == CURSOR
    assert all(r.url.params["search"] == "طرابلس +/&" for r in sent)
    assert all(not r.content for r in sent)
    assert b"%25D8" not in sent[0].url.query
    assert wire.key_document_requests == 0


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("amount_in", [DirectRechargeAmountIn.LYD, DirectRechargeAmountIn.FX])
async def test_quote_preserves_scale_and_amount_direction(mode: str, amount_in: DirectRechargeAmountIn) -> None:
    wire = SignedMockWire(lambda request: answer(quote()))
    async with product_client(mode, wire) as client:
        result = await resolved(
            client.direct_recharge_products.quote(
                wallet_id=WALLET, product_id=OPERATION, amount="1500.000", amount_in=amount_in
            )
        )
        assert result.exchange_rate == "0.155000"
        assert result.payout.amount == "1500.000"
        assert result.payout.currency.name == "جنيه مصري"
        with pytest.raises(ValueError, match="amount_in must be lyd or fx"):
            await resolved(
                client.direct_recharge_products.quote(WALLET, OPERATION, "1500.000", DirectRechargeAmountIn.UNKNOWN)
            )
    assert len(api_requests(wire)) == 1
    assert dict(api_requests(wire)[0].url.params) == {"amount": "1500.000", "amountIn": amount_in.value}
    assert wire.key_document_requests == 0


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_product_and_location_iterators_refuse_no_progress(mode: str) -> None:
    wire = SignedMockWire(lambda request: answer({"items": [], "nextCursor": CURSOR}))
    async with product_client(mode, wire) as client:
        for iterator in (
            client.direct_recharge_products.get_direct_recharge_products(
                WALLET, DirectRechargeProductsQuery(cursor=CURSOR)
            ),
            client.direct_recharge_products.get_direct_recharge_product_locations(
                WALLET, OPERATION, DirectRechargeLocationsQuery(cursor=CURSOR)
            ),
        ):
            with pytest.raises(MalformedResponseError):
                await collected(iterator)
    assert len(api_requests(wire)) == 2


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("bound", ["minimumTotal", "maximumTotal", "minimumPayout", "maximumPayout", None])
async def test_partial_limits_through_both_product_getters(mode: str, bound: str | None) -> None:
    limits = (
        {} if bound is None else {bound: {"amount": "1.000", "currency": "LYD"} if bound.endswith("Total") else "1.000"}
    )
    data = {**product(), "limits": limits}
    wire = SignedMockWire(lambda request: answer({"items": [data], "nextCursor": None}))
    async with product_client(mode, wire) as client:
        page = await resolved(client.direct_recharge_products.get_direct_recharge_products_page(WALLET))
        assert page.items[0].limits.to_json() == limits
        assert page.items[0].to_json() == data
        detail = {**data, "recipientFields": [{"key": "OptionalField", "kind": "text", "for": "recipient", "order": 1}]}
        wire.answer = lambda request: answer(detail)
        result = await resolved(client.direct_recharge_products.get(wallet_id=WALLET, product_id=OPERATION))
        assert result.limits.to_json() == limits
        assert result.recipient_fields[0].name is None
        assert result.to_json() == detail
