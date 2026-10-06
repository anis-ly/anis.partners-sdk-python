"""Custom exceptions remain safe to copy, serialize, and place inside outcome dataclasses."""

from __future__ import annotations

import copy
import pickle
from dataclasses import asdict
from datetime import timedelta
from typing import get_type_hints
from uuid import UUID

import pytest

from anis_partners import (
    AnisApiError,
    AnisPartnersError,
    AuthorizationError,
    DependencyUnavailableError,
    EnrollmentKeyMismatchError,
    EnrollmentRefusedError,
    IdempotencyConflictError,
    InsufficientBalanceError,
    InvalidCredentialsError,
    KeyDocumentUnavailableError,
    LimitExceededError,
    MalformedResponseError,
    OrderNotPlaced,
    OrderOutcomeUnknown,
    OutOfStockError,
    PriceChangedError,
    RateLimitedError,
    ReplayDetectedError,
    RequestSigningError,
    ResourceNotFoundError,
    ResponseVerificationFailure,
    UnverifiableResponseError,
    ValidationFailedError,
)
from anis_partners.models import Problem

API_ERRORS = (
    AnisApiError,
    InsufficientBalanceError,
    PriceChangedError,
    OutOfStockError,
    IdempotencyConflictError,
    RateLimitedError,
    LimitExceededError,
    InvalidCredentialsError,
    ReplayDetectedError,
    AuthorizationError,
    ResourceNotFoundError,
    ValidationFailedError,
    DependencyUnavailableError,
    EnrollmentRefusedError,
)


def _api_error(error_type: type[AnisApiError]) -> AnisApiError:
    return error_type(Problem(title="Refused", status=409, code="price_changed", request_id="req-123"), 409)


def _pickle_round_trip(error: Exception) -> object:
    payload = pickle.dumps(error)
    return pickle.loads(payload)  # noqa: S301 - payload is created from this trusted test value above.


@pytest.mark.parametrize("error_type", API_ERRORS, ids=lambda error_type: error_type.__name__)
def test_api_refusals_survive_copy_deepcopy_and_pickle(error_type: type[AnisApiError]) -> None:
    error = _api_error(error_type)

    for rebuilt in (copy.copy(error), copy.deepcopy(error), _pickle_round_trip(error)):
        assert type(rebuilt) is error_type
        assert rebuilt.raw_code == "price_changed"
        assert rebuilt.status == 409
        assert rebuilt.request_id == "req-123"


@pytest.mark.parametrize(
    "error",
    [
        AnisPartnersError("base failure"),
        RequestSigningError("signing failed"),
        UnverifiableResponseError(ResponseVerificationFailure.SIGNATURE_INVALID),
        EnrollmentKeyMismatchError("local-thumbprint", "server-thumbprint"),
        KeyDocumentUnavailableError("key document unavailable"),
        MalformedResponseError("verified answer did not match its model"),
    ],
    ids=["base", "request-signing", "unverifiable-response", "enrollment-key-mismatch", "key-document", "malformed"],
)
def test_other_sdk_exceptions_survive_copy_deepcopy_and_pickle(error: Exception) -> None:
    for rebuilt in (copy.copy(error), copy.deepcopy(error), _pickle_round_trip(error)):
        assert type(rebuilt) is type(error)
        if isinstance(error, UnverifiableResponseError):
            assert isinstance(rebuilt, UnverifiableResponseError)
            assert rebuilt.failure is error.failure
        if isinstance(error, EnrollmentKeyMismatchError):
            assert isinstance(rebuilt, EnrollmentKeyMismatchError)
            assert rebuilt.local_thumbprint == error.local_thumbprint
            assert rebuilt.server_thumbprint == error.server_thumbprint


def test_order_refusal_survives_asdict() -> None:
    operation_id = UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")
    refusal = _api_error(PriceChangedError)
    result = OrderNotPlaced(operation_id, refusal)

    copied = asdict(result)["refusal"]

    assert isinstance(copied, PriceChangedError)
    assert copied.raw_code == "price_changed"
    assert copied.status == 409


def test_order_not_placed_exposes_a_resolvable_public_refusal_type() -> None:
    """Keep reflection-based partner tools able to inspect refusals without private imports."""
    assert get_type_hints(OrderNotPlaced)["refusal"] is AnisPartnersError


def test_unknown_order_cause_survives_asdict() -> None:
    operation_id = UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")
    cause = _api_error(DependencyUnavailableError)
    result = OrderOutcomeUnknown(operation_id, timedelta(seconds=5), cause)

    copied = asdict(result)["cause"]

    assert isinstance(copied, DependencyUnavailableError)
    assert copied.raw_code == "price_changed"
