"""Sync and async response verification against every released response vector."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from anis_partners.verification.errors import UnverifiableResponseError
from anis_partners.verification.partner_jwk import SigningKeySet
from anis_partners.verification.partner_response_verifier import (
    AsyncPartnerResponseVerifier,
    PartnerResponseVerifier,
)
from anis_partners.verification.verifiable_response import VerifiableResponse
from tests.support.vectors import read_vector, vector_files


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

    def refresh(self) -> SigningKeySet:
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

    async def refresh(self) -> SigningKeySet:
        """Return vector keys after an unknown key request."""
        self.refresh_calls += 1
        return self._keys


def _subject(vector: dict[str, object]) -> VerifiableResponse:
    """Build the buffered received response represented by a vector."""
    response = vector["response"]
    assert isinstance(response, dict)
    request = vector["request"]
    assert isinstance(request, dict)
    return VerifiableResponse(
        status=response["status"],
        headers=response["headers"],
        body=__import__("base64").b64decode(response["bodyBase64"]),
        request_signature_input=request["signatureInput"],
    )


def _keys(vector: dict[str, object]) -> SigningKeySet:
    """Parse the response vector's published key document."""
    return SigningKeySet.from_json(__import__("json").dumps(vector["signingKeys"]))


def _expected(vector: dict[str, object]) -> str | None:
    expected = vector["expected"]
    assert isinstance(expected, dict)
    return expected["reason"] if expected["outcome"] == "reject" else None


def test_response_vector_file_count_is_thirty_nine() -> None:
    """Fail if the response corpus is incomplete."""
    assert len(vector_files("response", "RS")) == 39


@pytest.mark.parametrize("path", vector_files("response", "RS"), ids=lambda path: Path(path).stem)
def test_sync_verifier_reaches_each_declared_vector_outcome(path: Path) -> None:
    """Check one response vector through the synchronous verifier."""
    vector = read_vector(path)
    keys = StaticKeys(_keys(vector))
    verifier = PartnerResponseVerifier(keys, FixedClock(vector["verifyAt"]))
    reason = _expected(vector)
    if reason is None:
        verifier.verify(_subject(vector))
    else:
        with pytest.raises(UnverifiableResponseError) as caught:
            verifier.verify(_subject(vector))
        assert caught.value.failure.value == reason


@pytest.mark.anyio
@pytest.mark.parametrize("path", vector_files("response", "RS"), ids=lambda path: Path(path).stem)
async def test_async_verifier_reaches_each_declared_vector_outcome(path: Path) -> None:
    """Check one response vector through the asynchronous verifier."""
    vector = read_vector(path)
    keys = AsyncStaticKeys(_keys(vector))
    verifier = AsyncPartnerResponseVerifier(keys, FixedClock(vector["verifyAt"]))
    reason = _expected(vector)
    if reason is None:
        await verifier.verify(_subject(vector))
    else:
        with pytest.raises(UnverifiableResponseError) as caught:
            await verifier.verify(_subject(vector))
        assert caught.value.failure.value == reason


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on the required asyncio backend."""
    return "asyncio"
