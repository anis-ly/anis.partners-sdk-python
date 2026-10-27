"""Sync and async webhook verification against the shared webhook conformance corpus."""

import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from anis_partners.models.webhooks import WebhookEnvelope, WebhookEventType
from anis_partners.verification.partner_jwk import SigningKeySet
from anis_partners.verification.partner_webhook_verifier import AsyncPartnerWebhookVerifier, PartnerWebhookVerifier
from anis_partners.verification.verifiable_webhook import VerifiableWebhook
from anis_partners.verification.webhook_errors import UnverifiableWebhookError
from anis_partners.verification.webhook_failures import WebhookVerificationFailure
from tests.support.vectors import ROOT, read_vector, vector_files

CORPUS = vector_files("webhook", "WH")
KNOWN_TYPES = {item.value for item in WebhookEventType} - {WebhookEventType.UNKNOWN.value}


class FixedClock:
    """Returns a fixed aware UTC time for vector verification."""

    def __init__(self, epoch: int) -> None:
        self._now = datetime.fromtimestamp(epoch, UTC)

    def now(self) -> datetime:
        """Return the vector's verification time."""
        return self._now


class StaticKeys:
    """Provides an in-memory vector key set."""

    def __init__(self, keys: SigningKeySet) -> None:
        self._keys = keys
        self.refresh_calls = 0

    def get(self) -> SigningKeySet:
        """Return vector keys."""
        return self._keys

    def refresh(self, previous: SigningKeySet | None = None) -> SigningKeySet:
        """Return vector keys after an unknown key request."""
        self.refresh_calls += 1
        return self._keys


class AsyncStaticKeys:
    """Provides an asynchronous in-memory vector key set."""

    def __init__(self, keys: SigningKeySet) -> None:
        self._keys = keys
        self.refresh_calls = 0

    async def get(self) -> SigningKeySet:
        """Return vector keys."""
        return self._keys

    async def refresh(self, previous: SigningKeySet | None = None) -> SigningKeySet:
        """Return vector keys after an unknown key request."""
        self.refresh_calls += 1
        return self._keys


def _subject(vector: dict[str, Any]) -> VerifiableWebhook:
    """Build the received delivery from the exact body bytes, never from the readable body text."""
    request = vector["request"]
    return VerifiableWebhook(
        method=request["method"],
        target_uri=request["targetUri"],
        headers=request["headers"],
        body=base64.b64decode(request["bodyBase64"], validate=True),
    )


def _configuration(vector: dict[str, Any]) -> dict[str, Any]:
    receiver = vector["receiver"]
    return {"configured_url": receiver["configuredUrl"], "application_id": receiver["applicationId"]}


def _keys(vector: dict[str, Any]) -> SigningKeySet:
    return SigningKeySet.from_json(json.dumps(vector["signingKeys"]))


def _phase(vector: dict[str, Any]) -> str:
    return str(vector["expected"].get("phase", "verify"))


def _reason(vector: dict[str, Any]) -> str | None:
    expected = vector["expected"]
    return expected["reason"] if expected["outcome"] == "reject" else None


def _assert_envelope(vector: dict[str, Any], envelope: WebhookEnvelope) -> None:
    """Check identity, discriminator and data preservation of an accepted delivery."""
    expected = vector["expected"]["envelope"]
    assert envelope.id == UUID(expected["id"])
    assert envelope.application_id == UUID(expected["applicationId"])
    assert (envelope.raw_type or envelope.type.value) == expected["type"]
    if expected["type"] in KNOWN_TYPES:
        assert envelope.type.value == expected["type"]
    else:
        assert envelope.type is WebhookEventType.UNKNOWN
    assert envelope.to_json()["data"] == json.loads(expected["dataRaw"])


def test_corpus_is_present_exhaustive_and_matches_its_manifest() -> None:
    """Require the shipped corpus, its index and the files on disk to agree exactly."""
    directory = ROOT / "webhook"
    manifest = read_vector(directory / "manifest.json")
    vectors = [read_vector(path) for path in CORPUS]
    assert len(vectors) == 75
    assert manifest["total"] == len(vectors)
    assert manifest["accept"] == sum(_reason(vector) is None for vector in vectors)
    assert manifest["reject"] == sum(_reason(vector) is not None for vector in vectors)
    assert manifest["accept"] == 20
    assert manifest["reject"] == 55
    assert (manifest["profile"], manifest["algorithm"], manifest["label"]) == (
        "anis-partner-webhook-v1",
        "ecdsa-p256-sha256",
        "sig1",
    )
    assert (manifest["skewSeconds"], manifest["lifetimeSeconds"]) == (300, 300)
    on_disk = {path.name for path in directory.iterdir() if path.name != "manifest.json"}
    assert on_disk == {path.name for path in CORPUS}
    by_id = {entry["id"]: entry for entry in manifest["vectors"]}
    assert len(by_id) == len(vectors)
    for vector in vectors:
        entry = by_id[vector["id"]]
        assert entry["outcome"] == vector["expected"]["outcome"]
        assert entry["reason"] == vector["expected"]["reason"]
        assert entry.get("phase", "verify") == _phase(vector)
    reasons = {_reason(vector) for vector in vectors} - {None}
    assert reasons == {item.value for item in WebhookVerificationFailure}


@pytest.mark.parametrize("path", CORPUS, ids=lambda path: Path(path).stem)
def test_sync_verifier_reaches_each_declared_vector_outcome(path: Path) -> None:
    """Check one delivery through the synchronous verifier, in both verification phases."""
    vector = read_vector(path)
    keys = StaticKeys(_keys(vector))
    verifier = PartnerWebhookVerifier(keys, clock=FixedClock(vector["verifyAt"]), **_configuration(vector))
    reason = _reason(vector)
    if reason is None:
        verifier.verify(_subject(vector))
        _assert_envelope(vector, verifier.verify_and_parse(_subject(vector)))
    elif _phase(vector) == "parse":
        verifier.verify(_subject(vector))
        with pytest.raises(UnverifiableWebhookError) as caught:
            verifier.verify_and_parse(_subject(vector))
        assert caught.value.failure.value == reason
    else:
        for call in (verifier.verify, verifier.verify_and_parse):
            with pytest.raises(UnverifiableWebhookError) as caught:
                call(_subject(vector))
            assert caught.value.failure.value == reason


@pytest.mark.anyio
@pytest.mark.parametrize("path", CORPUS, ids=lambda path: Path(path).stem)
async def test_async_verifier_reaches_each_declared_vector_outcome(path: Path) -> None:
    """Check one delivery through the asynchronous verifier, in both verification phases."""
    vector = read_vector(path)
    keys = AsyncStaticKeys(_keys(vector))
    verifier = AsyncPartnerWebhookVerifier(keys, clock=FixedClock(vector["verifyAt"]), **_configuration(vector))
    reason = _reason(vector)
    if reason is None:
        await verifier.verify(_subject(vector))
        _assert_envelope(vector, await verifier.verify_and_parse(_subject(vector)))
    elif _phase(vector) == "parse":
        await verifier.verify(_subject(vector))
        with pytest.raises(UnverifiableWebhookError) as caught:
            await verifier.verify_and_parse(_subject(vector))
        assert caught.value.failure.value == reason
    else:
        with pytest.raises(UnverifiableWebhookError) as caught:
            await verifier.verify(_subject(vector))
        assert caught.value.failure.value == reason
        with pytest.raises(UnverifiableWebhookError) as caught:
            await verifier.verify_and_parse(_subject(vector))
        assert caught.value.failure.value == reason


def test_webhook_corpus_matches_the_published_hash() -> None:
    directory = ROOT / "webhook"
    files = sorted(directory.glob("*.json"))
    assert len(files) == 76
    listing = "".join(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n" for path in files)
    assert (
        hashlib.sha256(listing.encode()).hexdigest()
        == "a598d6a274516bc28e4afadf40978048a99bea0f604d84140229494739fc3cfa"
    )
