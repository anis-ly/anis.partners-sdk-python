"""Published JWK validation and refresh behavior."""

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime, tzinfo

import pytest

from anis_partners.verification.errors import UnverifiableResponseError
from anis_partners.verification.failures import ResponseVerificationFailure
from anis_partners.verification.partner_jwk import SigningKeySet
from anis_partners.verification.partner_response_verifier import PartnerResponseVerifier
from anis_partners.verification.signature_input_parser import parse as parse_signature_input
from anis_partners.verification.verifiable_response import VerifiableResponse
from tests.support.responses import response_fixture

_BASE64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_BASE64URL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def _alter_unused_base64_bits(value: str, alphabet: str) -> str:
    """Keep decoded bytes while changing only bits canonical base64 requires to be zero."""
    padding = len(value) - len(value.rstrip("="))
    last = len(value) - padding - 1
    index = alphabet.index(value[last])
    return value[:last] + alphabet[(index & ~15) | 1] + value[last + 1 :]


class FixedClock:
    """Returns a vector timestamp."""

    def __init__(self, epoch: int | datetime) -> None:
        self.value = datetime.fromtimestamp(epoch, UTC) if isinstance(epoch, int) else epoch

    def now(self) -> datetime:
        """Return an aware UTC time."""
        return self.value


class RotatingKeys:
    """Returns a stale set first, then the rotated published set."""

    def __init__(self, initial: SigningKeySet, refreshed: SigningKeySet) -> None:
        self.initial = initial
        self.refreshed = refreshed
        self.refresh_count = 0

    def get(self) -> SigningKeySet:
        """Return the initial cached set."""
        return self.initial

    def refresh(self, previous: SigningKeySet | None = None) -> SigningKeySet:
        """Return the refreshed set and count the refresh."""
        self.refresh_count += 1
        return self.refreshed


def test_off_curve_public_point_is_key_rejected() -> None:
    """Valid-width coordinates that do not form a P-256 point are refused."""
    vector = response_fixture()
    full = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    response_data = vector["response"]
    key_id = response_data["headers"]["Signature-Input"].split('keyid="')[1].split('"')[0]
    changed = tuple(replace(key, x="A" * 43, y="A" * 43) if key.kid == key_id else key for key in full.keys)
    response = VerifiableResponse(
        response_data["status"],
        response_data["headers"],
        base64.b64decode(response_data["bodyBase64"]),
        vector["request"]["signatureInput"],
        vector["request"]["signature"],
    )
    with pytest.raises(UnverifiableResponseError) as caught:
        PartnerResponseVerifier(
            RotatingKeys(SigningKeySet(changed), SigningKeySet(changed)), FixedClock(vector["verifyAt"])
        ).verify(response)
    assert caught.value.failure is ResponseVerificationFailure.KEY_REJECTED


def test_unknown_key_causes_exactly_one_refresh() -> None:
    """An unknown key triggers the rotation recovery once and then succeeds."""
    vector = response_fixture()
    full = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    active_kid = vector["response"]["headers"]["Signature-Input"].split('keyid="')[1].split('"')[0]
    initial = SigningKeySet(tuple(key for key in full.keys if key.kid != active_kid))
    response_data = vector["response"]
    response = VerifiableResponse(
        response_data["status"],
        response_data["headers"],
        base64.b64decode(response_data["bodyBase64"]),
        vector["request"]["signatureInput"],
        vector["request"]["signature"],
    )
    source = RotatingKeys(initial, full)
    PartnerResponseVerifier(source, FixedClock(vector["verifyAt"])).verify(response)
    assert source.refresh_count == 1


def test_private_member_in_stale_document_is_checked_after_refresh() -> None:
    """A stale private-bearing document cannot block recovery to a clean rotated set."""
    vector = response_fixture()
    full = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    headers = vector["response"]["headers"]
    active_kid = headers["Signature-Input"].split('keyid="')[1].split('"')[0]
    other = next(key for key in full.keys if key.kid != active_kid)
    stale_keys = tuple(
        replace(key, d="private") if key.kid == other.kid else key for key in full.keys if key.kid != active_kid
    )
    response_data = vector["response"]
    response = VerifiableResponse(
        response_data["status"],
        response_data["headers"],
        base64.b64decode(response_data["bodyBase64"]),
        vector["request"]["signatureInput"],
        vector["request"]["signature"],
    )
    source = RotatingKeys(SigningKeySet(stale_keys), full)
    PartnerResponseVerifier(source, FixedClock(vector["verifyAt"])).verify(response)
    assert source.refresh_count == 1


def test_empty_private_member_does_not_reject_the_key_document() -> None:
    """An empty private field carries no private key material and remains acceptable."""
    vector = response_fixture()
    full = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    active_kid = vector["response"]["headers"]["Signature-Input"].split('keyid="')[1].split('"')[0]
    keys = SigningKeySet(tuple(replace(key, d="") if key.kid == active_kid else key for key in full.keys))
    response_data = vector["response"]
    response = VerifiableResponse(
        response_data["status"],
        response_data["headers"],
        base64.b64decode(response_data["bodyBase64"]),
        vector["request"]["signatureInput"],
        vector["request"]["signature"],
    )
    PartnerResponseVerifier(RotatingKeys(keys, keys), FixedClock(vector["verifyAt"])).verify(response)


def test_freshness_uses_whole_seconds_at_the_boundary() -> None:
    """The 60-second limit matches whole-second timestamps used by .NET."""
    vector = response_fixture()
    keys = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    response_data = vector["response"]
    response = VerifiableResponse(
        response_data["status"],
        response_data["headers"],
        base64.b64decode(response_data["bodyBase64"]),
        vector["request"]["signatureInput"],
        vector["request"]["signature"],
    )
    created = int(response_data["headers"]["Signature-Input"].split(";created=")[1].split(";")[0])
    source = RotatingKeys(keys, keys)
    PartnerResponseVerifier(
        source, FixedClock(datetime.fromtimestamp(created + 60, UTC).replace(microsecond=999000))
    ).verify(response)
    with pytest.raises(UnverifiableResponseError) as caught:
        PartnerResponseVerifier(
            source, FixedClock(datetime.fromtimestamp(created + 61, UTC).replace(microsecond=999000))
        ).verify(response)
    assert caught.value.failure is ResponseVerificationFailure.CREATED_OUT_OF_WINDOW


def test_numeric_extra_parameter_does_not_replace_created() -> None:
    """An unknown numeric parameter cannot replace a fresh signature time and pass verification."""
    vector = response_fixture()
    response_data = vector["response"]
    headers = dict(response_data["headers"])
    original = headers["Signature-Input"]
    created = original.split(";created=")[1].split(";")[0]
    headers["Signature-Input"] = original.replace(f";created={created}", f";created=1;extra={created}")
    response = VerifiableResponse(
        response_data["status"],
        headers,
        base64.b64decode(response_data["bodyBase64"]),
        vector["request"]["signatureInput"],
        vector["request"]["signature"],
    )
    keys = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    with pytest.raises(UnverifiableResponseError) as caught:
        PartnerResponseVerifier(RotatingKeys(keys, keys), FixedClock(vector["verifyAt"])).verify(response)
    assert caught.value.failure is ResponseVerificationFailure.CREATED_OUT_OF_WINDOW


def test_signature_with_trailing_junk_is_malformed() -> None:
    """A valid signature followed by extra text is refused instead of verifying its inner bytes."""
    vector = response_fixture()
    response_data = vector["response"]
    headers = dict(response_data["headers"])
    headers["Signature"] += "junk"
    response = VerifiableResponse(
        response_data["status"],
        headers,
        base64.b64decode(response_data["bodyBase64"]),
        vector["request"]["signatureInput"],
        vector["request"]["signature"],
    )
    keys = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    with pytest.raises(UnverifiableResponseError) as caught:
        PartnerResponseVerifier(RotatingKeys(keys, keys), FixedClock(vector["verifyAt"])).verify(response)
    assert caught.value.failure is ResponseVerificationFailure.SIGNATURE_MALFORMED


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Signature", ResponseVerificationFailure.SIGNATURE_MALFORMED),
        ("Content-Digest", ResponseVerificationFailure.CONTENT_DIGEST_MISMATCH),
    ],
)
def test_noncanonical_standard_base64_is_refused_with_its_declared_reason(
    header: str, expected: ResponseVerificationFailure
) -> None:
    """Refuse alternate standard-base64 spellings so one digest or signature has only one wire form."""
    vector = response_fixture()
    response_data = vector["response"]
    headers = dict(response_data["headers"])
    if header == "Signature":
        value = headers[header]
        encoded = value.removeprefix("sig1=:").removesuffix(":")
        headers[header] = "sig1=:" + _alter_unused_base64_bits(encoded, _BASE64) + ":"
    else:
        value = headers[header]
        encoded = value.removeprefix("sha-256=:").removesuffix(":")
        headers[header] = "sha-256=:" + _alter_unused_base64_bits(encoded, _BASE64) + ":"
    response = VerifiableResponse(
        response_data["status"],
        headers,
        base64.b64decode(response_data["bodyBase64"]),
        vector["request"]["signatureInput"],
        vector["request"]["signature"],
    )
    keys = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    with pytest.raises(UnverifiableResponseError) as caught:
        PartnerResponseVerifier(RotatingKeys(keys, keys), FixedClock(vector["verifyAt"])).verify(response)
    assert caught.value.failure is expected


def test_noncanonical_jwk_coordinate_is_key_rejected() -> None:
    """Refuse alternate JWK coordinate spellings even when a permissive decoder would yield the same point."""
    vector = response_fixture()
    response_data = vector["response"]
    headers = response_data["headers"]
    key_id = headers["Signature-Input"].split('keyid="')[1].split('"')[0]
    document = vector["signingKeys"]
    document["keys"] = [
        {**key, "x": _alter_unused_base64_bits(key["x"], _BASE64URL)} if key["kid"] == key_id else key
        for key in document["keys"]
    ]
    keys = SigningKeySet.from_json(json.dumps(document))
    response = VerifiableResponse(
        response_data["status"],
        headers,
        base64.b64decode(response_data["bodyBase64"]),
        vector["request"]["signatureInput"],
        vector["request"]["signature"],
    )
    with pytest.raises(UnverifiableResponseError) as caught:
        PartnerResponseVerifier(RotatingKeys(keys, keys), FixedClock(vector["verifyAt"])).verify(response)
    assert caught.value.failure is ResponseVerificationFailure.KEY_REJECTED


def test_created_parameter_over_python_integer_limit_is_malformed() -> None:
    """Reject huge attacker-controlled numbers before integer parsing can expose runtime details."""
    value = f'sig1=("@method");created={"9" * 5000};keyid="{"1" * 36}"'
    assert parse_signature_input(value) is None


@pytest.mark.parametrize("tag", [None, "anis-response-v1", "unexpected"])
def test_response_profile_requires_the_exact_v2_tag(tag: str | None) -> None:
    """Refuse missing or foreign response profiles before trusting the key or body."""
    vector = response_fixture()
    headers = vector["response"]["headers"]
    replacement = "" if tag is None else f';tag="{tag}"'
    headers["Signature-Input"] = headers["Signature-Input"].replace(';tag="anis-response-v2"', replacement)
    keys = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    from anis_partners.verification.partner_response_verifier import verify_response

    response = VerifiableResponse(
        200, headers, b"{}", vector["request"]["signatureInput"], vector["request"]["signature"]
    )
    assert (
        verify_response(response, keys, FixedClock(vector["verifyAt"]).now())
        is ResponseVerificationFailure.PROFILE_UNEXPECTED
    )


@pytest.mark.parametrize(
    ("status", "offset", "expected"),
    [
        ("retired", -1, ResponseVerificationFailure.KEY_RETIRED),
        ("retired", 0, None),
        ("retired", 1, None),
        ("next", 1, ResponseVerificationFailure.KEY_NOT_YET_VALID),
        ("next", 0, None),
        ("next", -1, None),
        ("active", 1, ResponseVerificationFailure.KEY_NOT_YET_VALID),
    ],
)
@pytest.mark.anyio
async def test_key_lifecycle_boundaries_match_in_both_verifiers(
    status: str,
    offset: int,
    expected: ResponseVerificationFailure | None,
) -> None:
    """Accept boundary instants and reject only signatures outside the published signing window."""
    from anis_partners.models._json import wire_timestamp
    from anis_partners.verification.partner_response_verifier import AsyncPartnerResponseVerifier
    from tests.conformance.test_response_vectors import AsyncStaticKeys

    vector = response_fixture()
    keys_json = vector["signingKeys"]
    key = keys_json["keys"][0]
    key["status"] = status
    instant = wire_timestamp(datetime.fromtimestamp(vector["verifyAt"] + offset, UTC))
    key["retiredAt" if status == "retired" else "notBefore"] = instant
    keys = SigningKeySet.from_json(json.dumps(keys_json))
    response = VerifiableResponse(
        200, vector["response"]["headers"], b"{}", vector["request"]["signatureInput"], vector["request"]["signature"]
    )
    sync = PartnerResponseVerifier(RotatingKeys(keys, keys), FixedClock(vector["verifyAt"]))
    async_verifier = AsyncPartnerResponseVerifier(AsyncStaticKeys(keys), FixedClock(vector["verifyAt"]))
    if expected is None:
        sync.verify(response)
        await async_verifier.verify(response)
    else:
        with pytest.raises(UnverifiableResponseError) as caught:
            sync.verify(response)
        assert caught.value.failure is expected
        with pytest.raises(UnverifiableResponseError) as caught:
            await async_verifier.verify(response)
        assert caught.value.failure is expected


@pytest.mark.parametrize("status", ["active", "next", "retired"])
@pytest.mark.parametrize("offset", [0, 1])
@pytest.mark.anyio
async def test_any_published_key_used_before_not_before_is_not_yet_valid_in_both_verifiers(
    status: str, offset: int
) -> None:
    """Every published key must already be valid when the response was signed, including at the boundary."""
    from anis_partners.models._json import wire_timestamp
    from anis_partners.verification.partner_response_verifier import AsyncPartnerResponseVerifier
    from tests.conformance.test_response_vectors import AsyncStaticKeys

    vector = response_fixture()
    document = vector["signingKeys"]
    key = document["keys"][0]
    key["status"] = status
    key["notBefore"] = wire_timestamp(datetime.fromtimestamp(vector["verifyAt"] + offset, UTC))
    if status == "retired":
        key["retiredAt"] = wire_timestamp(datetime.fromtimestamp(vector["verifyAt"] + 100, UTC))
    keys = SigningKeySet.from_json(json.dumps(document))
    response = VerifiableResponse(
        200, vector["response"]["headers"], b"{}", vector["request"]["signatureInput"], vector["request"]["signature"]
    )
    sync = PartnerResponseVerifier(RotatingKeys(keys, keys), FixedClock(vector["verifyAt"]))
    async_verifier = AsyncPartnerResponseVerifier(AsyncStaticKeys(keys), FixedClock(vector["verifyAt"]))
    if offset == 0:
        sync.verify(response)
        await async_verifier.verify(response)
    else:
        with pytest.raises(UnverifiableResponseError) as caught:
            sync.verify(response)
        assert caught.value.failure is ResponseVerificationFailure.KEY_NOT_YET_VALID
        with pytest.raises(UnverifiableResponseError) as caught:
            await async_verifier.verify(response)
        assert caught.value.failure is ResponseVerificationFailure.KEY_NOT_YET_VALID


@pytest.mark.parametrize("status", ["active", "next", "retired"])
@pytest.mark.parametrize("fraction", ["0000", "0001", "0000000", "0000001"])
@pytest.mark.anyio
async def test_fractional_not_before_requires_the_next_whole_created_second_in_both_verifiers(
    status: str, fraction: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key activated just after a whole second cannot authenticate a signature created at that second."""
    import tests.support.sdk_wire as wire_module
    from anis_partners.verification.partner_response_verifier import AsyncPartnerResponseVerifier
    from tests.conformance.test_response_vectors import AsyncStaticKeys

    class FixedSigningTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> "FixedSigningTime":
            return cls(2026, 10, 12, 12, tzinfo=UTC)

    monkeypatch.setattr(wire_module, "datetime", FixedSigningTime)

    vector = response_fixture()
    document = vector["signingKeys"]
    key = document["keys"][0]
    key["status"] = status
    key["notBefore"] = f"2026-10-12T12:00:00.{fraction}Z"
    if status == "retired":
        key["retiredAt"] = "2026-10-12T12:01:00Z"
    keys = SigningKeySet.from_json(json.dumps(document))
    response = VerifiableResponse(
        200, vector["response"]["headers"], b"{}", vector["request"]["signatureInput"], vector["request"]["signature"]
    )
    created = int(response.headers["Signature-Input"].split(";created=")[1].split(";")[0])
    assert datetime.fromtimestamp(created, UTC) == datetime(2026, 10, 12, 12, tzinfo=UTC)
    sync = PartnerResponseVerifier(RotatingKeys(keys, keys), FixedClock(created))
    async_verifier = AsyncPartnerResponseVerifier(AsyncStaticKeys(keys), FixedClock(created))
    if int(fraction) == 0:
        sync.verify(response)
        await async_verifier.verify(response)
    else:
        with pytest.raises(UnverifiableResponseError) as caught:
            sync.verify(response)
        assert caught.value.failure is ResponseVerificationFailure.KEY_NOT_YET_VALID
        with pytest.raises(UnverifiableResponseError) as caught:
            await async_verifier.verify(response)
        assert caught.value.failure is ResponseVerificationFailure.KEY_NOT_YET_VALID


@pytest.mark.parametrize("listed", [True, False])
@pytest.mark.anyio
async def test_compromised_key_is_refused_without_refresh_even_if_unlisted(listed: bool) -> None:
    """A revocation overrides available key material and cannot be evaded through an unknown-key refresh."""
    from anis_partners.models._json import wire_timestamp
    from anis_partners.verification.partner_response_verifier import AsyncPartnerResponseVerifier
    from tests.conformance.test_response_vectors import AsyncStaticKeys

    vector = response_fixture()
    document = vector["signingKeys"]
    document["revoked"] = [
        {
            "kid": document["keys"][0]["kid"],
            "compromisedAt": wire_timestamp(datetime.fromtimestamp(vector["verifyAt"] + 10, UTC)),
        }
    ]
    if not listed:
        document["keys"] = []
    keys = SigningKeySet.from_json(json.dumps(document))
    response = VerifiableResponse(
        200, vector["response"]["headers"], b"{}", vector["request"]["signatureInput"], vector["request"]["signature"]
    )
    sync_source = RotatingKeys(keys, keys)
    async_source = AsyncStaticKeys(keys)
    with pytest.raises(UnverifiableResponseError) as caught:
        PartnerResponseVerifier(sync_source, FixedClock(vector["verifyAt"])).verify(response)
    assert caught.value.failure is ResponseVerificationFailure.KEY_COMPROMISED
    with pytest.raises(UnverifiableResponseError) as caught:
        await AsyncPartnerResponseVerifier(async_source, FixedClock(vector["verifyAt"])).verify(response)
    assert caught.value.failure is ResponseVerificationFailure.KEY_COMPROMISED
    assert sync_source.refresh_count == async_source.refresh_calls == 0


def test_response_binds_the_raw_request_signature_after_signature_input() -> None:
    """Changing a request signature under identical request parameters prevents response substitution."""
    from anis_partners.verification.partner_response_verifier import verify_response

    vector = response_fixture()
    keys = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    response = VerifiableResponse(
        200, vector["response"]["headers"], b"{}", vector["request"]["signatureInput"], vector["request"]["signature"]
    )
    assert '"signature-input";req "signature";req' in response.headers["Signature-Input"]
    assert (
        verify_response(
            replace(response, request_signature="sig1=:different:"), keys, FixedClock(vector["verifyAt"]).now()
        )
        is ResponseVerificationFailure.SIGNATURE_INVALID
    )
    assert (
        verify_response(replace(response, request_signature=None), keys, FixedClock(vector["verifyAt"]).now())
        is ResponseVerificationFailure.COVERED_COMPONENTS_MISMATCH
    )


@pytest.mark.parametrize(
    ("status", "member", "value"),
    [
        ("active", "status", None),
        ("active", "status", "unknown"),
        ("active", "status", 1),
        ("next", "notBefore", None),
        ("next", "notBefore", "not-a-date"),
        ("next", "notBefore", "NaN"),
        ("retired", "retiredAt", None),
        ("retired", "retiredAt", "not-a-date"),
        ("retired", "retiredAt", "NaN"),
    ],
)
@pytest.mark.anyio
async def test_incomplete_matched_key_lifecycle_is_key_rejected_in_both_verifiers(
    status: str,
    member: str,
    value: object,
) -> None:
    """Refuse malformed status, activation or retirement metadata before applying signing-window comparisons."""
    from anis_partners.verification.partner_response_verifier import AsyncPartnerResponseVerifier
    from tests.conformance.test_response_vectors import AsyncStaticKeys

    vector = response_fixture()
    document = vector["signingKeys"]
    key = document["keys"][0]
    key["status"] = status
    if value is None:
        key.pop(member, None)
    else:
        key[member] = value
    keys = SigningKeySet.from_json(json.dumps(document))
    response = VerifiableResponse(
        200, vector["response"]["headers"], b"{}", vector["request"]["signatureInput"], vector["request"]["signature"]
    )
    sync_source = RotatingKeys(keys, keys)
    async_source = AsyncStaticKeys(keys)
    with pytest.raises(UnverifiableResponseError) as caught:
        PartnerResponseVerifier(sync_source, FixedClock(vector["verifyAt"])).verify(response)
    assert caught.value.failure is ResponseVerificationFailure.KEY_REJECTED
    with pytest.raises(UnverifiableResponseError) as caught:
        await AsyncPartnerResponseVerifier(async_source, FixedClock(vector["verifyAt"])).verify(response)
    assert caught.value.failure is ResponseVerificationFailure.KEY_REJECTED
    assert sync_source.refresh_count == async_source.refresh_calls == 0


def test_host_key_source_cannot_bypass_lifecycle_validation_with_a_naive_datetime() -> None:
    """Custom key sources receive the same timestamp validation as fetched key documents."""
    vector = response_fixture()
    document = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    keys = SigningKeySet((replace(document.keys[0], not_before=datetime(2026, 1, 1)),))
    response = VerifiableResponse(
        200, vector["response"]["headers"], b"{}", vector["request"]["signatureInput"], vector["request"]["signature"]
    )
    with pytest.raises(UnverifiableResponseError) as caught:
        PartnerResponseVerifier(RotatingKeys(keys, keys), FixedClock(vector["verifyAt"])).verify(response)
    assert caught.value.failure is ResponseVerificationFailure.KEY_REJECTED


@pytest.mark.anyio
@pytest.mark.parametrize("purpose", [None, "answer"], ids=["legacy-omitted", "emitted-answer"])
async def test_optional_purpose_preserves_answer_verification_and_key_round_trip(purpose: str | None) -> None:
    from anis_partners.verification.partner_response_verifier import AsyncPartnerResponseVerifier
    from tests.conformance.test_response_vectors import AsyncStaticKeys

    vector = response_fixture()
    for item in vector["signingKeys"]["keys"]:
        if purpose is None:
            item.pop("purpose", None)
        else:
            item["purpose"] = purpose
    keys = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    assert all(key.purpose == purpose for key in keys.keys)
    serialized = [key.to_json() for key in keys.keys]
    assert all(("purpose" not in key if purpose is None else key["purpose"] == purpose) for key in serialized)
    restored = SigningKeySet.from_json(json.dumps({"keys": serialized}))
    assert restored == keys
    response = VerifiableResponse(
        200, vector["response"]["headers"], b"{}", vector["request"]["signatureInput"], vector["request"]["signature"]
    )
    sync_keys = RotatingKeys(restored, restored)
    async_keys = AsyncStaticKeys(restored)
    PartnerResponseVerifier(sync_keys, FixedClock(vector["verifyAt"])).verify(response)
    await AsyncPartnerResponseVerifier(async_keys, FixedClock(vector["verifyAt"])).verify(response)
    assert sync_keys.refresh_count == async_keys.refresh_calls == 0


@pytest.mark.anyio
@pytest.mark.parametrize("purpose", ["webhook", "", "Answer"], ids=["webhook", "empty", "wrong-case"])
async def test_key_published_for_another_purpose_cannot_verify_an_api_answer(purpose: str) -> None:
    from anis_partners.verification.partner_response_verifier import AsyncPartnerResponseVerifier
    from tests.conformance.test_response_vectors import AsyncStaticKeys

    vector = response_fixture()
    for item in vector["signingKeys"]["keys"]:
        item["purpose"] = purpose
    keys = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    response = VerifiableResponse(
        200, vector["response"]["headers"], b"{}", vector["request"]["signatureInput"], vector["request"]["signature"]
    )
    sync_keys = RotatingKeys(keys, keys)
    async_keys = AsyncStaticKeys(keys)
    with pytest.raises(UnverifiableResponseError) as caught:
        PartnerResponseVerifier(sync_keys, FixedClock(vector["verifyAt"])).verify(response)
    assert caught.value.failure is ResponseVerificationFailure.KEY_REJECTED
    with pytest.raises(UnverifiableResponseError) as caught:
        await AsyncPartnerResponseVerifier(async_keys, FixedClock(vector["verifyAt"])).verify(response)
    assert caught.value.failure is ResponseVerificationFailure.KEY_REJECTED
    assert sync_keys.refresh_count == async_keys.refresh_calls == 0


@pytest.mark.anyio
async def test_submicrosecond_retirement_does_not_extend_the_retired_key_window() -> None:
    from anis_partners.verification.partner_response_verifier import AsyncPartnerResponseVerifier
    from tests.conformance.test_response_vectors import AsyncStaticKeys

    vector = response_fixture()
    created = int(vector["response"]["headers"]["Signature-Input"].split(";created=")[1].split(";")[0])
    document = vector["signingKeys"]
    key = document["keys"][0]
    key["status"] = "retired"
    key["retiredAt"] = datetime.fromtimestamp(created - 1, UTC).strftime("%Y-%m-%dT%H:%M:%S") + ".9999999Z"
    keys = SigningKeySet.from_json(json.dumps(document))
    assert keys.keys[0].retired_at is not None
    assert keys.keys[0].retired_at.microsecond == 999999
    response = VerifiableResponse(
        200, vector["response"]["headers"], b"{}", vector["request"]["signatureInput"], vector["request"]["signature"]
    )
    with pytest.raises(UnverifiableResponseError) as caught:
        PartnerResponseVerifier(RotatingKeys(keys, keys), FixedClock(vector["verifyAt"])).verify(response)
    assert caught.value.failure is ResponseVerificationFailure.KEY_RETIRED
    with pytest.raises(UnverifiableResponseError) as caught:
        await AsyncPartnerResponseVerifier(AsyncStaticKeys(keys), FixedClock(vector["verifyAt"])).verify(response)
    assert caught.value.failure is ResponseVerificationFailure.KEY_RETIRED
