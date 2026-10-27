"""Sign modified webhook bodies for compatibility and receiver integration tests."""

import base64
import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from anis_partners._internal.base64url import encode
from anis_partners.signing.ecdsa_signature_format import der_to_p1363
from anis_partners.verification.partner_jwk import SigningKeySet
from anis_partners.verification.partner_webhook_signature_base import build, parameters
from anis_partners.verification.verifiable_webhook import VerifiableWebhook
from tests.support.products import NOW

APPLICATION = UUID("9b2d1241-413e-4ae8-ae32-b15c58dbe101")
URL = "https://receiver.example/hooks/anis?registration=1%2B2"


class FixedClock:
    def now(self) -> datetime:
        return NOW


def signed_delivery(
    data: dict[str, Any], event_type: str, *, target: str = URL
) -> tuple[VerifiableWebhook, SigningKeySet]:
    key = ec.generate_private_key(ec.SECP256R1())
    point = key.public_key().public_numbers()
    key_id = "test-webhook/key-1"
    event_id = str(UUID(int=77))
    created = int(NOW.timestamp())
    body = json.dumps(
        {
            "id": event_id,
            "type": event_type,
            "occurredAt": NOW.isoformat().replace("+00:00", "Z"),
            "applicationId": str(APPLICATION),
            "data": data,
        },
        ensure_ascii=False,
    ).encode()
    digest = "sha-256=:" + base64.b64encode(hashlib.sha256(body).digest()).decode() + ":"
    signature = der_to_p1363(
        key.sign(
            build(target, digest, event_id, "1", str(APPLICATION), created, created + 300, key_id),
            ec.ECDSA(hashes.SHA256()),
        )
    )
    delivery = VerifiableWebhook(
        "POST",
        target,
        {
            "Content-Digest": digest,
            "Webhook-Id": event_id,
            "Anis-Webhook-Attempt": "1",
            "Anis-Application-Id": str(APPLICATION),
            "Signature-Input": "sig1=" + parameters(created, created + 300, key_id),
            "Signature": "sig1=:" + base64.b64encode(signature).decode() + ":",
        },
        body,
    )
    keys = SigningKeySet.from_json(
        json.dumps(
            {
                "keys": [
                    {
                        "kty": "EC",
                        "crv": "P-256",
                        "x": encode(point.x.to_bytes(32, "big")),
                        "y": encode(point.y.to_bytes(32, "big")),
                        "kid": key_id,
                        "status": "active",
                        "notBefore": datetime(2026, 10, 19, tzinfo=UTC).isoformat(),
                        "purpose": "webhook",
                    }
                ],
                "revoked": [],
            }
        )
    )
    return delivery, keys
