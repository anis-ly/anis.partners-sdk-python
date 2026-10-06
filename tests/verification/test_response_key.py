"""Published JWK validation and refresh behavior."""

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from anis_partners.verification.errors import UnverifiableResponseError
from anis_partners.verification.failures import ResponseVerificationFailure
from anis_partners.verification.partner_jwk import SigningKeySet
from anis_partners.verification.partner_response_verifier import PartnerResponseVerifier
from anis_partners.verification.signature_input_parser import parse as parse_signature_input
from anis_partners.verification.verifiable_response import VerifiableResponse
from tests.support.vectors import read_vector, vector_files

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
    vector_path = next(
        path for path in vector_files("response", "RS") if path.name == "RS-001-safe-read-profile-200.json"
    )
    vector = read_vector(vector_path)
    full = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    response_data = vector["response"]
    key_id = response_data["headers"]["Signature-Input"].split('keyid="')[1].split('"')[0]
    changed = tuple(replace(key, x="A" * 43, y="A" * 43) if key.kid == key_id else key for key in full.keys)
    response = VerifiableResponse(
        response_data["status"],
        response_data["headers"],
        base64.b64decode(response_data["bodyBase64"]),
        vector["request"]["signatureInput"],
    )
    with pytest.raises(UnverifiableResponseError) as caught:
        PartnerResponseVerifier(
            RotatingKeys(SigningKeySet(changed), SigningKeySet(changed)), FixedClock(vector["verifyAt"])
        ).verify(response)
    assert caught.value.failure is ResponseVerificationFailure.KEY_REJECTED


def test_unknown_key_causes_exactly_one_refresh() -> None:
    """An unknown key triggers the rotation recovery once and then succeeds."""
    vector_path = next(path for path in vector_files("response", "RS") if "RS-101" in path.name)
    vector = read_vector(vector_path)
    full = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    active_kid = vector["response"]["headers"]["Signature-Input"].split('keyid="')[1].split('"')[0]
    initial = SigningKeySet(tuple(key for key in full.keys if key.kid != active_kid))
    response_data = vector["response"]
    response = VerifiableResponse(
        response_data["status"],
        response_data["headers"],
        base64.b64decode(response_data["bodyBase64"]),
        vector["request"]["signatureInput"],
    )
    source = RotatingKeys(initial, full)
    PartnerResponseVerifier(source, FixedClock(vector["verifyAt"])).verify(response)
    assert source.refresh_count == 1


def test_private_member_in_stale_document_is_checked_after_refresh() -> None:
    """A stale private-bearing document cannot block recovery to a clean rotated set."""
    vector_path = next(
        path for path in vector_files("response", "RS") if path.name == "RS-001-safe-read-profile-200.json"
    )
    vector = read_vector(vector_path)
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
    )
    source = RotatingKeys(SigningKeySet(stale_keys), full)
    PartnerResponseVerifier(source, FixedClock(vector["verifyAt"])).verify(response)
    assert source.refresh_count == 1


def test_empty_private_member_does_not_reject_the_key_document() -> None:
    """An empty private field carries no private key material and remains acceptable."""
    vector_path = next(
        path for path in vector_files("response", "RS") if path.name == "RS-001-safe-read-profile-200.json"
    )
    vector = read_vector(vector_path)
    full = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    active_kid = vector["response"]["headers"]["Signature-Input"].split('keyid="')[1].split('"')[0]
    keys = SigningKeySet(tuple(replace(key, d="") if key.kid == active_kid else key for key in full.keys))
    response_data = vector["response"]
    response = VerifiableResponse(
        response_data["status"],
        response_data["headers"],
        base64.b64decode(response_data["bodyBase64"]),
        vector["request"]["signatureInput"],
    )
    PartnerResponseVerifier(RotatingKeys(keys, keys), FixedClock(vector["verifyAt"])).verify(response)


def test_freshness_uses_whole_seconds_at_the_boundary() -> None:
    """The 60-second limit matches whole-second timestamps used by .NET."""
    vector_path = next(
        path for path in vector_files("response", "RS") if path.name == "RS-001-safe-read-profile-200.json"
    )
    vector = read_vector(vector_path)
    keys = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    response_data = vector["response"]
    response = VerifiableResponse(
        response_data["status"],
        response_data["headers"],
        base64.b64decode(response_data["bodyBase64"]),
        vector["request"]["signatureInput"],
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
    vector_path = next(
        path for path in vector_files("response", "RS") if path.name == "RS-001-safe-read-profile-200.json"
    )
    vector = read_vector(vector_path)
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
    )
    keys = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    with pytest.raises(UnverifiableResponseError) as caught:
        PartnerResponseVerifier(RotatingKeys(keys, keys), FixedClock(vector["verifyAt"])).verify(response)
    assert caught.value.failure is ResponseVerificationFailure.CREATED_OUT_OF_WINDOW


def test_signature_with_trailing_junk_is_malformed() -> None:
    """A valid signature followed by extra text is refused instead of verifying its inner bytes."""
    vector_path = next(
        path for path in vector_files("response", "RS") if path.name == "RS-001-safe-read-profile-200.json"
    )
    vector = read_vector(vector_path)
    response_data = vector["response"]
    headers = dict(response_data["headers"])
    headers["Signature"] += "junk"
    response = VerifiableResponse(
        response_data["status"],
        headers,
        base64.b64decode(response_data["bodyBase64"]),
        vector["request"]["signatureInput"],
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
    vector_path = next(
        path for path in vector_files("response", "RS") if path.name == "RS-001-safe-read-profile-200.json"
    )
    vector = read_vector(vector_path)
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
    )
    keys = SigningKeySet.from_json(json.dumps(vector["signingKeys"]))
    with pytest.raises(UnverifiableResponseError) as caught:
        PartnerResponseVerifier(RotatingKeys(keys, keys), FixedClock(vector["verifyAt"])).verify(response)
    assert caught.value.failure is expected


def test_noncanonical_jwk_coordinate_is_key_rejected() -> None:
    """Refuse alternate JWK coordinate spellings even when a permissive decoder would yield the same point."""
    vector_path = next(
        path for path in vector_files("response", "RS") if path.name == "RS-001-safe-read-profile-200.json"
    )
    vector = read_vector(vector_path)
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
    )
    with pytest.raises(UnverifiableResponseError) as caught:
        PartnerResponseVerifier(RotatingKeys(keys, keys), FixedClock(vector["verifyAt"])).verify(response)
    assert caught.value.failure is ResponseVerificationFailure.KEY_REJECTED


def test_created_parameter_over_python_integer_limit_is_malformed() -> None:
    """Reject huge attacker-controlled numbers before integer parsing can expose runtime details."""
    value = f'sig1=("@method");created={"9" * 5000};keyid="{"1" * 36}"'
    assert parse_signature_input(value) is None
