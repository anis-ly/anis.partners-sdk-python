"""Webhook verification rules that the shared corpus does not express directly."""

import base64
import copy
import json
import pickle
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from anis_partners.models.direct_recharges import DirectRecharge, DirectRechargeStatus
from anis_partners.models.webhooks import WebhookEventType
from anis_partners.verification.partner_jwk import PublishedSigningKey, SigningKeySet
from anis_partners.verification.partner_webhook_verifier import (
    AsyncPartnerWebhookVerifier,
    PartnerWebhookVerifier,
    verify_webhook,
)
from anis_partners.verification.verifiable_webhook import VerifiableWebhook
from anis_partners.verification.webhook_errors import UnverifiableWebhookError
from anis_partners.verification.webhook_failures import WebhookVerificationFailure
from tests.support.vectors import ROOT, read_vector

DIRECTORY = ROOT / "webhook"
APPLICATION = "9b2d1241-413e-4ae8-ae32-b15c58dbe101"


class FixedClock:
    """Returns a fixed aware UTC time."""

    def __init__(self, epoch: int) -> None:
        self._now = datetime.fromtimestamp(epoch, UTC)

    def now(self) -> datetime:
        """Return the vector's verification time."""
        return self._now


class CountingKeys:
    """Provides a key set and counts refreshes."""

    def __init__(self, keys: SigningKeySet) -> None:
        self.keys = keys
        self.refresh_calls = 0

    def get(self) -> SigningKeySet:
        """Return the held keys."""
        return self.keys

    def refresh(self, previous: SigningKeySet | None = None) -> SigningKeySet:
        """Count the refresh and return the held keys."""
        self.refresh_calls += 1
        return self.keys


class AsyncCountingKeys:
    """Provides a key set asynchronously and counts refreshes."""

    def __init__(self, keys: SigningKeySet) -> None:
        self.keys = keys
        self.refresh_calls = 0

    async def get(self) -> SigningKeySet:
        """Return the held keys."""
        return self.keys

    async def refresh(self, previous: SigningKeySet | None = None) -> SigningKeySet:
        """Count the refresh and return the held keys."""
        self.refresh_calls += 1
        return self.keys


def _vector(name: str) -> dict[str, Any]:
    return read_vector(next(DIRECTORY.glob(f"{name}*.json")))


def _delivery(vector: dict[str, Any]) -> VerifiableWebhook:
    request = vector["request"]
    return VerifiableWebhook(
        request["method"], request["targetUri"], dict(request["headers"]), base64.b64decode(request["bodyBase64"])
    )


def _verifier(vector: dict[str, Any], keys: CountingKeys | None = None, **overrides: Any) -> PartnerWebhookVerifier:
    receiver = vector["receiver"]
    keys = keys or CountingKeys(SigningKeySet.from_json(json.dumps(vector["signingKeys"])))
    options = {"configured_url": receiver["configuredUrl"], "application_id": receiver["applicationId"]}
    options.update(overrides)
    return PartnerWebhookVerifier(keys, clock=FixedClock(vector["verifyAt"]), **options)


def test_suspended_type_with_current_in_progress_data_is_accepted() -> None:
    """A suspended notification may carry the later inProgress read; the verified data is the truth."""
    vector = _vector("WH-046")
    envelope = _verifier(vector).verify_and_parse(_delivery(vector))
    assert envelope.type is WebhookEventType.DIRECT_RECHARGE_SUSPENDED
    assert isinstance(envelope.data, DirectRecharge)
    assert envelope.data.status is DirectRechargeStatus.IN_PROGRESS


@pytest.mark.anyio
async def test_async_unknown_webhook_type_is_preserved_after_verification() -> None:
    """An unknown future type is accepted once verified and exposes its raw type and data."""
    vector = _vector("WH-034")
    receiver = vector["receiver"]
    keys = AsyncCountingKeys(SigningKeySet.from_json(json.dumps(vector["signingKeys"])))
    verifier = AsyncPartnerWebhookVerifier(
        keys,
        configured_url=receiver["configuredUrl"],
        application_id=UUID(receiver["applicationId"]),
        clock=FixedClock(vector["verifyAt"]),
    )
    envelope = await verifier.verify_and_parse(_delivery(vector))
    assert envelope.type is WebhookEventType.UNKNOWN
    assert envelope.raw_type == "future.receipt.ready"
    assert isinstance(envelope.data, dict)
    assert envelope.data["future"][1]["text"] == "عربي"


def test_raw_arabic_bytes_are_verified_without_reserialisation() -> None:
    """The digest covers the received bytes, so a re-encoded body is refused."""
    vector = _vector("WH-049")
    delivery = _delivery(vector)
    _verifier(vector).verify(delivery)
    reserialised = json.dumps(json.loads(delivery.body), ensure_ascii=False, indent=1).encode()
    changed = VerifiableWebhook(delivery.method, delivery.target_uri, delivery.headers, reserialised)
    with pytest.raises(UnverifiableWebhookError) as caught:
        _verifier(vector).verify(changed)
    assert caught.value.failure is WebhookVerificationFailure.CONTENT_DIGEST_MISMATCH


def test_unknown_key_refreshes_once_and_known_key_does_not_refresh() -> None:
    """A published key never triggers key-document I/O, while an unpublished one is refreshed once."""
    known = _vector("WH-001")
    keys = CountingKeys(SigningKeySet.from_json(json.dumps(known["signingKeys"])))
    _verifier(known, keys).verify(_delivery(known))
    assert keys.refresh_calls == 0
    unknown = _vector("WH-028")
    keys = CountingKeys(SigningKeySet.from_json(json.dumps(unknown["signingKeys"])))
    with pytest.raises(UnverifiableWebhookError) as caught:
        _verifier(unknown, keys).verify(_delivery(unknown))
    assert caught.value.failure is WebhookVerificationFailure.UNKNOWN_KEY
    assert keys.refresh_calls == 1


def test_configured_url_and_application_never_come_from_the_request() -> None:
    """Request headers cannot widen what the receiver is configured to accept."""
    vector = _vector("WH-001")
    delivery = _delivery(vector)
    other_url = _verifier(vector, configured_url=delivery.target_uri + "?x=1")
    with pytest.raises(UnverifiableWebhookError) as caught:
        other_url.verify(delivery)
    assert caught.value.failure is WebhookVerificationFailure.TARGET_URI_MISMATCH
    other_application = _verifier(vector, application_id=UUID(int=7))
    with pytest.raises(UnverifiableWebhookError) as caught:
        other_application.verify(delivery)
    assert caught.value.failure is WebhookVerificationFailure.APPLICATION_ID_MISMATCH
    forwarded = VerifiableWebhook(
        delivery.method, delivery.target_uri, {**delivery.headers, "X-Forwarded-Host": "evil.example"}, delivery.body
    )
    _verifier(vector).verify(forwarded)


def test_a_malformed_configured_application_is_refused_at_construction() -> None:
    """A misconfigured receiver fails loudly instead of silently accepting nothing."""
    vector = _vector("WH-001")
    with pytest.raises(ValueError, match="UUID"):
        _verifier(vector, application_id="not-a-uuid")


def test_pure_verification_returns_the_first_failure_without_key_io() -> None:
    """The pure helper mirrors the verifier phases and performs no refresh."""
    vector = _vector("WH-012")
    keys = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    receiver = vector["receiver"]
    failure = verify_webhook(
        _delivery(vector),
        keys,
        datetime.fromtimestamp(vector["verifyAt"], UTC),
        configured_url=receiver["configuredUrl"],
        application_id=receiver["applicationId"],
    )
    assert failure is WebhookVerificationFailure.KEY_RETIRED
    good = _vector("WH-001")
    assert (
        verify_webhook(
            _delivery(good),
            SigningKeySet.from_json(json.dumps(good["signingKeys"])),
            datetime.fromtimestamp(good["verifyAt"], UTC),
            configured_url=good["receiver"]["configuredUrl"],
            application_id=good["receiver"]["applicationId"],
        )
        is None
    )


def test_verify_and_parse_reads_nothing_from_a_failed_delivery() -> None:
    """A failed verification raises before any envelope member is read or exposed."""
    vector = _vector("WH-003")
    with pytest.raises(UnverifiableWebhookError) as caught:
        _verifier(vector).verify_and_parse(_delivery(vector))
    assert caught.value.failure is WebhookVerificationFailure.CONTENT_DIGEST_MISMATCH
    assert "meterCharge" not in str(caught.value)
    assert "meterCharge" not in repr(_delivery(vector))


def test_unverifiable_webhook_error_survives_pickling() -> None:
    """The bounded reason is kept when an exception crosses a process boundary."""
    error = pickle.loads(pickle.dumps(UnverifiableWebhookError(WebhookVerificationFailure.SIGNATURE_EXPIRED)))  # noqa: S301
    assert error.failure is WebhookVerificationFailure.SIGNATURE_EXPIRED


def test_published_key_keeps_purpose_and_purpose_less_documents_still_parse() -> None:
    """The additive purpose member round-trips and old purpose-less documents remain valid."""
    vector = _vector("WH-001")
    document = copy.deepcopy(vector["signingKeys"])
    keys = SigningKeySet.from_json(json.dumps(document))
    assert keys.keys[0].purpose == "webhook"
    assert keys.keys[0].to_json()["purpose"] == "webhook"
    without = {key: value for key, value in document["keys"][0].items() if key != "purpose"}
    legacy = PublishedSigningKey.from_json(without)
    assert legacy.purpose is None
    assert "purpose" not in legacy.to_json()
    assert PublishedSigningKey("EC", "P-256", "x", "y", "kid").purpose is None


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("phase", ["verify", "verify_and_parse"])
@pytest.mark.parametrize(
    ("member", "failure"),
    [
        ("attempt", WebhookVerificationFailure.COVERED_COMPONENTS_MISMATCH),
        ("created", WebhookVerificationFailure.SIGNATURE_MALFORMED),
        ("expires", WebhookVerificationFailure.VALIDITY_WINDOW_INVALID),
    ],
)
@pytest.mark.parametrize("digits", ["9" * 5000, "0" * 5000 + "1"])
async def test_oversized_numeric_headers_return_structured_failures(
    mode: str, phase: str, member: str, failure: WebhookVerificationFailure, digits: str
) -> None:
    import re

    vector = _vector("WH-001")
    original = _delivery(vector)
    headers = dict(original.headers)
    header = next(
        name
        for name in headers
        if name.lower() == ("anis-webhook-attempt" if member == "attempt" else "signature-input")
    )
    headers[header] = (
        digits if member == "attempt" else re.sub(member + r"=[0-9]+", member + "=" + digits, headers[header])
    )
    delivery = VerifiableWebhook(original.method, original.target_uri, headers, original.body)
    document = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    receiver = vector["receiver"]
    verifier = (
        _verifier(vector)
        if mode == "sync"
        else AsyncPartnerWebhookVerifier(
            AsyncCountingKeys(document),
            clock=FixedClock(vector["verifyAt"]),
            configured_url=receiver["configuredUrl"],
            application_id=receiver["applicationId"],
        )
    )
    call = getattr(verifier, phase)
    if mode == "sync":
        with pytest.raises(UnverifiableWebhookError) as caught:
            call(delivery)
    else:
        with pytest.raises(UnverifiableWebhookError) as caught:
            await call(delivery)
    assert caught.value.failure is failure
    assert (
        verify_webhook(
            delivery,
            document,
            datetime.fromtimestamp(vector["verifyAt"], UTC),
            configured_url=receiver["configuredUrl"],
            application_id=receiver["applicationId"],
        )
        is failure
    )


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("null", [False, True], ids=["omitted", "null"])
@pytest.mark.parametrize("kind", ["recipient", "receipt", "failure"])
async def test_verified_webhooks_accept_optional_product_members(mode: str, null: bool, kind: str) -> None:
    from tests.support.products import full_read
    from tests.support.webhooks import APPLICATION, URL, signed_delivery
    from tests.support.webhooks import FixedClock as ProductClock

    data = full_read(kind != "recipient")
    if kind == "recipient":
        target = data["recipient"][0]
        members = ["name"]
        event_type = "directRecharge.completed"
    elif kind == "receipt":
        target = data["receipt"]
        members = ["receiptNumber", "creditedAmount"]
        event_type = "meterCharge.succeeded"
    else:
        from tests.support.products import fixture

        data = fixture("meter-failed-refunded")
        target = data["failure"]
        members = ["message"]
        event_type = "meterCharge.failed"
    for member in members:
        if null:
            target[member] = None
        else:
            target.pop(member, None)
    delivery, keys = signed_delivery(data, event_type)
    verifier = (
        PartnerWebhookVerifier(CountingKeys(keys), configured_url=URL, application_id=APPLICATION, clock=ProductClock())
        if mode == "sync"
        else AsyncPartnerWebhookVerifier(
            AsyncCountingKeys(keys), configured_url=URL, application_id=APPLICATION, clock=ProductClock()
        )
    )
    if isinstance(verifier, AsyncPartnerWebhookVerifier):
        envelope = await verifier.verify_and_parse(delivery)
    else:
        envelope = verifier.verify_and_parse(delivery)
    expected = copy.deepcopy(data)
    expected_target = expected["recipient"][0] if kind == "recipient" else expected[kind]
    for member in members:
        expected_target.pop(member, None)
    assert envelope.to_json()["data"] == expected


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_one_tick_activation_remains_future_after_key_serialization(mode: str) -> None:
    vector = _vector("WH-069")
    keys = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    assert keys.keys[0].not_before is not None
    assert keys.keys[0].not_before.microsecond == 1
    restored = SigningKeySet.from_json(
        json.dumps({"keys": [key.to_json() for key in keys.keys], "revoked": vector["signingKeys"].get("revoked", [])})
    )
    assert restored == keys
    if mode == "sync":
        with pytest.raises(UnverifiableWebhookError) as caught:
            _verifier(vector, CountingKeys(restored)).verify(_delivery(vector))
    else:
        verifier = AsyncPartnerWebhookVerifier(
            AsyncCountingKeys(restored),
            configured_url=vector["receiver"]["configuredUrl"],
            application_id=vector["receiver"]["applicationId"],
            clock=FixedClock(vector["verifyAt"]),
        )
        with pytest.raises(UnverifiableWebhookError) as caught:
            await verifier.verify(_delivery(vector))
    assert caught.value.failure is WebhookVerificationFailure.KEY_NOT_YET_VALID
