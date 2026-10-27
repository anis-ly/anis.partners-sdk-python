"""Product fixtures and sync/async adapters over the existing in-memory signed wire."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from inspect import isawaitable
from pathlib import Path
from typing import Any, cast

import httpx

from anis_partners import (
    AnisPartnersClient,
    AsyncAnisPartnersClient,
    ClientOptions,
    CreateDirectRechargeRequest,
    CreateMeterChargeRequest,
    DirectRechargeRecipientInput,
    Money,
)
from tests.support.partner import CARD, OPERATION, SIGNER, WALLET
from tests.support.sdk_wire import SignedMockWire, WireAnswer

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "products"
NOW = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
CURSOR = "opaque+/=& طرابلس"


def fixture(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((FIXTURES / f"{name}.json").read_bytes()))


def money(value: str = "97.500") -> Money:
    return Money.from_json({"amount": value, "currency": "LYD"})


def meter_request() -> CreateMeterChargeRequest:
    return CreateMeterChargeRequest(CARD, "0268000710262", money(), "POS-77")


def recharge_request() -> CreateDirectRechargeRequest:
    return CreateDirectRechargeRequest(
        CARD,
        "1500.000",
        money("237.500"),
        (DirectRechargeRecipientInput("recipient_number", "01012345678"),),
        note="Family support",
        external_reference="POS-77",
    )


def accepted(meter: bool = True) -> dict[str, object]:
    return {
        "operationId": str(OPERATION),
        "operationType": "meterCharge" if meter else "directRecharge",
        "status": "processing",
    }


def full_read(meter: bool = True, status: str | None = None) -> dict[str, Any]:
    data = fixture("meter-succeeded" if meter else "circle-completed")
    data["operationId"], data["walletId"] = str(OPERATION), str(WALLET)
    if status is not None:
        data["status"] = status
    return data


def answer(data: object, status: int = 200, headers: dict[str, str] | None = None) -> WireAnswer:
    return WireAnswer(status, json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode(), headers)


def problem(code: str, status: int, headers: dict[str, str] | None = None, **extra: object) -> WireAnswer:
    return answer({"code": code, "status": status, **extra}, status, headers)


@asynccontextmanager
async def product_client(mode: str, wire: SignedMockWire) -> AsyncIterator[Any]:
    if mode == "sync":
        with (
            httpx.Client(transport=wire.transport) as http,
            AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http) as client,
        ):
            yield client
    else:
        async with (
            httpx.AsyncClient(transport=wire.transport) as async_http,
            AsyncAnisPartnersClient(
                ClientOptions("https://partners.test"), SIGNER, http_client=async_http
            ) as async_client,
        ):
            yield async_client


async def resolved(result: Any) -> Any:
    return await result if isawaitable(result) else result


async def collected(result: Any) -> list[Any]:
    if hasattr(result, "__aiter__"):
        return [item async for item in result]
    return list(result)


def api_requests(wire: SignedMockWire) -> list[httpx.Request]:
    return [request for request in wire.requests if request.url.path != "/.well-known/partner-signing-keys.json"]
