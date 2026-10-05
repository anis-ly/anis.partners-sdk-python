"""In-memory HTTPX wire that signs test answers with a published P-256 key."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from anis_partners._internal.base64url import encode
from anis_partners.signing.ecdsa_signature_format import der_to_p1363
from anis_partners.verification.partner_response_signature_base import build, components, parameters

RESPONSE_KEY_ID = "partner-response-signing/v1-active"


@dataclass(slots=True)
class WireAnswer:
    """Define one response independently from the signature material added by the fake wire."""

    status: int = 200
    body: bytes = b"{}"
    headers: Mapping[str, str] | None = None


class SignedMockWire:
    """Record requests and produce authentic test responses so SDK tests exercise the real verifier."""

    def __init__(self, answer: Callable[[httpx.Request], WireAnswer] | None = None) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.answer = answer or (lambda request: WireAnswer())
        self.requests: list[httpx.Request] = []
        self.key_document_requests = 0
        self.transport = httpx.MockTransport(self.handle)

    def client(self, *, async_client: bool = False) -> httpx.Client | httpx.AsyncClient:
        """Build a client with no network access and the same mock wire for the API and key document."""
        if async_client:
            return httpx.AsyncClient(transport=self.transport)
        return httpx.Client(transport=self.transport)

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Sign each API response after observing request headers and exact request bytes."""
        self.requests.append(request)
        if request.url.path == "/.well-known/partner-signing-keys.json":
            self.key_document_requests += 1
            numbers = self.key.public_key().public_numbers()
            doc = {
                "keys": [
                    {
                        "kty": "EC",
                        "crv": "P-256",
                        "kid": RESPONSE_KEY_ID,
                        "x": encode(numbers.x.to_bytes(32, "big")),
                        "y": encode(numbers.y.to_bytes(32, "big")),
                    }
                ]
            }
            return httpx.Response(200, json=doc, request=request)
        answer = self.answer(request)
        headers = {name.lower(): value for name, value in (answer.headers or {}).items()}
        request_id = headers.setdefault("x-request-id", "req-test-001")
        digest = "sha-256=:" + base64.b64encode(hashlib.sha256(answer.body).digest()).decode("ascii") + ":"
        headers.setdefault("content-digest", digest)
        parts = components(
            answer.status,
            headers["content-digest"],
            request_id,
            request.headers.get("Signature-Input"),
            headers.get("location"),
            headers.get("retry-after"),
            headers.get("idempotency-replayed"),
            headers.get("cache-control"),
        )
        created = int(datetime.now(UTC).timestamp())
        params = parameters(parts, created, RESPONSE_KEY_ID)
        signature_base = build(parts, created, RESPONSE_KEY_ID)
        signature = der_to_p1363(self.key.sign(signature_base, ec.ECDSA(hashes.SHA256())))
        headers["signature-input"] = "sig1=" + params
        headers["signature"] = "sig1=:" + base64.b64encode(signature).decode("ascii") + ":"
        return httpx.Response(answer.status, headers=headers, content=answer.body, request=request)
