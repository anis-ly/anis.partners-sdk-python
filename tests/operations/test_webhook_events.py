"""Delivery paging and explicit redelivery keep endpoint control separate from purchases."""

from typing import Any

import httpx
import pytest

from anis_partners import (
    AnisApiError,
    MalformedResponseError,
    UnverifiableResponseError,
    WebhookDeliveryStatus,
    WebhookEventsQuery,
)
from tests.operations.test_signed_wire_capture import _wire_signature_verifies
from tests.support.partner import OPERATION
from tests.support.products import CURSOR, NOW, answer, api_requests, collected, problem, product_client, resolved
from tests.support.sdk_wire import SignedMockWire, WireAnswer

pytestmark = pytest.mark.anyio


def event() -> dict[str, Any]:
    return {
        "id": str(OPERATION),
        "type": "directRecharge.completed",
        "status": "failed",
        "attempts": 12,
        "lastAttemptAt": "2026-10-20T08:00:00Z",
        "nextAttemptAt": None,
        "lastResponseCode": 503,
        "lastFailureKind": "httpStatus",
    }


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_events_preserve_status_since_cursor_and_nullable_members(mode: str) -> None:
    count = 0

    def respond(request: httpx.Request) -> WireAnswer:
        nonlocal count
        count += 1
        return answer({"items": [event()], "nextCursor": CURSOR if count == 1 else None})

    wire = SignedMockWire(respond)
    async with product_client(mode, wire) as client:
        items = await collected(
            client.webhook_events.get_webhook_events(WebhookEventsQuery(WebhookDeliveryStatus.FAILED, NOW))
        )
        assert len(items) == 2
        assert items[0].to_json() == event()
    sent = api_requests(wire)
    assert dict(sent[0].url.params) == {"status": "failed", "since": "2026-10-20T08:00:00Z"}
    assert dict(sent[1].url.params) == {"status": "failed", "since": "2026-10-20T08:00:00Z", "cursor": CURSOR}
    assert wire.key_document_requests == 0
    for req in sent:
        assert req.content == b""
        _wire_signature_verifies(req)


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_events_empty_page_and_cursor_no_progress(mode: str) -> None:
    wire = SignedMockWire(lambda request: answer({"items": [], "nextCursor": None}))
    async with product_client(mode, wire) as client:
        page = await resolved(client.webhook_events.get_webhook_events_page())
        assert not page.items
        assert page.next_cursor is None
        assert await collected(client.webhook_events.get_webhook_events()) == []
        wire.answer = lambda request: answer({"items": [], "nextCursor": CURSOR})
        with pytest.raises(MalformedResponseError):
            await collected(client.webhook_events.get_webhook_events(WebhookEventsQuery(cursor=CURSOR)))
    assert wire.key_document_requests == 0


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_redeliver_signs_exact_empty_object_without_idempotency(mode: str) -> None:
    data = {"id": str(OPERATION), "status": "pending", "queuedAt": "2026-10-20T08:00:00Z"}
    wire = SignedMockWire(lambda request: answer(data, 202))
    async with product_client(mode, wire) as client:
        assert (await resolved(client.webhook_events.redeliver(OPERATION))).to_json() == data
    sent = api_requests(wire)
    assert len(sent) == 1
    assert sent[0].url.path == f"/v1/webhook-events/{OPERATION}/redeliver"
    assert sent[0].content == b"{}"
    assert sent[0].method == "POST"
    assert "Idempotency-Key" not in sent[0].headers
    _wire_signature_verifies(sent[0])


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("signing", ["gateway", "never"])
async def test_redeliver_requires_signed_refusal(mode: str, signing: Any) -> None:
    wire = SignedMockWire(lambda request: problem("webhook_endpoint_unverified", 409), signing=signing)
    async with product_client(mode, wire) as client:
        with pytest.raises(AnisApiError if signing == "gateway" else UnverifiableResponseError):
            await resolved(client.webhook_events.redeliver(OPERATION))
