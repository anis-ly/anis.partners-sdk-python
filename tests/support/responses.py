"""Fresh v2 response fixtures for unit checks independent from the released vector corpus."""

import base64
import json
from typing import Any

import httpx

from tests.support.sdk_wire import SignedMockWire


def response_fixture() -> dict[str, Any]:
    """Return a genuinely signed response, its request context, and three published versions."""
    wire = SignedMockWire(signing="always")
    request = httpx.Request(
        "GET",
        "https://partners.test/v1/orders/00000000-0000-0000-0000-000000000001",
        headers={"Signature-Input": 'sig1=("@method");created=1', "Signature": "sig1=:request-signature:"},
    )
    response = wire.handle(request)
    document = wire.handle(httpx.Request("GET", "https://partners.test/.well-known/partner-signing-keys.json")).json()
    active = document["keys"][0]
    document["keys"].extend([{**active, "kid": "unused-next"}, {**active, "kid": "unused-retired"}])
    created = int(response.headers["Signature-Input"].split(";created=")[1].split(";")[0])
    return {
        "response": {
            "status": response.status_code,
            "headers": {
                "Signature-Input": response.headers["Signature-Input"],
                "Signature": response.headers["Signature"],
                "Content-Digest": response.headers["Content-Digest"],
                "X-Request-Id": response.headers["X-Request-Id"],
            },
            "bodyBase64": base64.b64encode(response.content).decode(),
        },
        "request": {"signatureInput": request.headers["Signature-Input"], "signature": request.headers["Signature"]},
        "signingKeys": json.loads(json.dumps(document)),
        "verifyAt": created,
    }
