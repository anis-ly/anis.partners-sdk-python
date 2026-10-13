"""Self-service stops use the same signed wire and nonce profile as both client transports."""

import json
from typing import cast

import httpx
import pytest

from anis_partners import AnisPartnersClient, AsyncAnisPartnersClient, ClientOptions
from tests.operations.test_signed_wire_capture import _wire_signature_verifies
from tests.support.partner import CARD_SOLD, SIGNER
from tests.support.sdk_wire import SignedMockWire, WireAnswer


def _stop_wire() -> SignedMockWire:
    """Return signed current state for both application and credential stops."""
    return SignedMockWire(
        lambda request: WireAnswer(
            body=json.dumps(
                {
                    "applicationId": str(CARD_SOLD),
                    "keyId": str(CARD_SOLD),
                    "status": "suspended" if request.url.path.endswith("suspend") else "revoked",
                    "suspendedAt": "2026-10-11T09:00:00Z",
                    "revokedAt": "2026-10-11T09:00:00Z",
                }
            ).encode()
        )
    )


def _assert_stop_requests(wire: SignedMockWire) -> None:
    requests = [request for request in wire.requests if request.method == "POST"]
    assert [request.url.path for request in requests] == ["/v1/application/suspend", f"/v1/keys/{CARD_SOLD}/revoke"]
    for request in requests:
        assert request.content == b'{"reason":"Stop access"}'
        assert "Nonce" in request.headers
        assert "Idempotency-Key" not in request.headers
        assert request.headers["User-Agent"] == "anis-partners-python/2.0.1"
        assert request.headers["Signature-Input"].split(");")[0] == (
            'sig1=("@method" "@authority" "@path" "@query" "content-digest" "nonce" "x-anis-date"'
        )
        _wire_signature_verifies(request)


def test_sync_stops_sign_the_reason_body_and_return_verified_state() -> None:
    wire = _stop_wire()
    with (
        cast(httpx.Client, wire.client()) as http,
        AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http) as client,
    ):
        assert not hasattr(client, "application")
        assert not hasattr(client, "keys")
        suspended = client.access.suspend_application("  Stop access  ")
        revoked = client.access.revoke_key(CARD_SOLD, "  Stop access  ")
    assert suspended.application_id == revoked.key_id == CARD_SOLD
    assert suspended.status == "suspended"
    assert revoked.status == "revoked"
    assert suspended.suspended_at is not None
    assert revoked.revoked_at is not None
    _assert_stop_requests(wire)


@pytest.mark.anyio
async def test_async_stops_sign_the_reason_body_and_return_verified_state() -> None:
    wire = _stop_wire()
    async with (
        cast(httpx.AsyncClient, wire.client(async_client=True)) as http,
        AsyncAnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http) as client,
    ):
        assert not hasattr(client, "application")
        assert not hasattr(client, "keys")
        suspended = await client.access.suspend_application("  Stop access  ")
        revoked = await client.access.revoke_key(CARD_SOLD, "  Stop access  ")
    assert suspended.application_id == revoked.key_id == CARD_SOLD
    _assert_stop_requests(wire)


@pytest.mark.parametrize("reason", ["", " ", "x" * 501])
def test_invalid_stop_reason_is_rejected_before_http(reason: str) -> None:
    wire = _stop_wire()
    with (
        cast(httpx.Client, wire.client()) as http,
        AnisPartnersClient(ClientOptions("https://partners.test"), SIGNER, http_client=http) as client,
    ):
        with pytest.raises(ValueError, match="reason"):
            client.access.suspend_application(reason)
        with pytest.raises(ValueError, match="reason"):
            client.access.revoke_key(CARD_SOLD, reason)
    assert not wire.requests
