"""Typed RFC 9457 refusals and order safety decisions."""

import json
from datetime import timedelta

import pytest

from anis_partners.errors import (
    RETRYABLE_CODES,
    AnisApiError,
    AuthorizationError,
    DependencyUnavailableError,
    EnrollmentRefusedError,
    ErrorCode,
    IdempotencyConflictError,
    InsufficientBalanceError,
    InvalidCredentialsError,
    LimitExceededError,
    OrderRefusalOutcome,
    OutOfStockError,
    PriceChangedError,
    RateLimitedError,
    ReplayDetectedError,
    ResourceNotFoundError,
    ValidationFailedError,
    create_api_error,
    parse_error_code,
    parse_retry_after,
)

DECISIONS: dict[str, tuple[type[AnisApiError], OrderRefusalOutcome]] = {
    "insufficient_balance": (InsufficientBalanceError, OrderRefusalOutcome.NOT_PLACED),
    "price_changed": (PriceChangedError, OrderRefusalOutcome.NOT_PLACED),
    "quantity_unavailable": (OutOfStockError, OrderRefusalOutcome.NOT_PLACED),
    "card_unavailable": (OutOfStockError, OrderRefusalOutcome.NOT_PLACED),
    "owner_limit_exceeded": (LimitExceededError, OrderRefusalOutcome.NOT_PLACED),
    "daily_limit_exceeded": (LimitExceededError, OrderRefusalOutcome.NOT_PLACED),
    "allowed_debt_consent_required": (AnisApiError, OrderRefusalOutcome.NOT_PLACED),
    "purchase_not_allowed": (AuthorizationError, OrderRefusalOutcome.NOT_PLACED),
    "wallet_disabled": (AuthorizationError, OrderRefusalOutcome.NOT_PLACED),
    "wallet_expired": (AuthorizationError, OrderRefusalOutcome.NOT_PLACED),
    "business_subscription_required": (AuthorizationError, OrderRefusalOutcome.NOT_PLACED),
    "account_inactive": (AuthorizationError, OrderRefusalOutcome.NOT_PLACED),
    "binding_not_authorized": (AuthorizationError, OrderRefusalOutcome.NOT_PLACED),
    "currency_not_supported": (ValidationFailedError, OrderRefusalOutcome.NOT_PLACED),
    "idempotency_conflict": (IdempotencyConflictError, OrderRefusalOutcome.NOT_PLACED),
    "source_ip_not_allowed": (AuthorizationError, OrderRefusalOutcome.NOT_PLACED),
    "invalid_content_digest": (AnisApiError, OrderRefusalOutcome.NOT_PLACED),
    "validation_failed": (ValidationFailedError, OrderRefusalOutcome.NOT_PLACED),
    "resource_not_found": (ResourceNotFoundError, OrderRefusalOutcome.NOT_PLACED),
    "card_not_found": (ResourceNotFoundError, OrderRefusalOutcome.NOT_PLACED),
    "dependency_unavailable": (DependencyUnavailableError, OrderRefusalOutcome.UNKNOWN),
    "request_timeout": (DependencyUnavailableError, OrderRefusalOutcome.UNKNOWN),
    "internal_error": (DependencyUnavailableError, OrderRefusalOutcome.UNKNOWN),
    "operation_processing": (AnisApiError, OrderRefusalOutcome.UNKNOWN),
    "replay_detected": (ReplayDetectedError, OrderRefusalOutcome.UNKNOWN),
    "rate_limited": (RateLimitedError, OrderRefusalOutcome.UNKNOWN),
    "insufficient_scope": (AuthorizationError, OrderRefusalOutcome.UNKNOWN),
    "invalid_credentials": (InvalidCredentialsError, OrderRefusalOutcome.UNKNOWN),
    "signature_expired": (InvalidCredentialsError, OrderRefusalOutcome.UNKNOWN),
    "wallet_not_granted": (ResourceNotFoundError, OrderRefusalOutcome.UNKNOWN),
    "malformed_signed_request": (AnisApiError, OrderRefusalOutcome.UNKNOWN),
    "reveal_not_allowed": (AuthorizationError, OrderRefusalOutcome.NOT_PLACED),
    "invoice_reveal_limit_exceeded": (AnisApiError, OrderRefusalOutcome.NOT_PLACED),
    "invitation_invalid": (EnrollmentRefusedError, OrderRefusalOutcome.NOT_PLACED),
    "challenge_expired": (EnrollmentRefusedError, OrderRefusalOutcome.NOT_PLACED),
    "key_proof_invalid": (EnrollmentRefusedError, OrderRefusalOutcome.NOT_PLACED),
    "key_duplicate": (EnrollmentRefusedError, OrderRefusalOutcome.NOT_PLACED),
}


def test_every_public_code_has_a_deliberate_decision() -> None:
    """Fail closed when the catalogue adds a code without a typed error and order classification."""
    public_codes = {member.value for member in ErrorCode if member is not ErrorCode.UNKNOWN}
    assert public_codes == set(DECISIONS)


@pytest.mark.parametrize("raw_code", sorted(DECISIONS), ids=sorted(DECISIONS))
def test_a_code_becomes_its_decided_error_and_order_outcome(raw_code: str) -> None:
    """Make every public code produce the error and order meaning partners are expected to catch."""
    expected_type, expected_outcome = DECISIONS[raw_code]
    body = json.dumps({"type": "about:blank", "title": "t", "status": 409, "code": raw_code, "requestId": "01J9"})
    failure = create_api_error(body.encode(), 409, {})
    assert type(failure) is expected_type
    assert failure.order_outcome is expected_outcome
    assert failure.raw_code == raw_code
    assert failure.request_id == "01J9"


def test_an_unknown_code_is_open_and_not_assumed_retryable() -> None:
    """Keep a future code visible while requiring safe same-id order recovery."""
    failure = create_api_error(b'{"code":"a_code_from_the_future"}', 409, {})
    assert type(failure) is AnisApiError
    assert failure.code is ErrorCode.UNKNOWN
    assert failure.raw_code == "a_code_from_the_future"
    assert failure.order_outcome is OrderRefusalOutcome.UNKNOWN
    assert not failure.is_retryable
    assert parse_error_code("a_code_from_the_future") is ErrorCode.UNKNOWN


@pytest.mark.parametrize(
    ("code", "status"),
    [("internal_error", 500), ("a_code_from_the_future", 409), ("replay_detected", 409)],
)
def test_a_replayed_refusal_is_closed_whatever_its_code(code: str, status: int) -> None:
    """Treat Anis's recorded refusal as final because repeating it returns that same answer forever."""
    failure = create_api_error(
        json.dumps({"status": status, "code": code, "requestId": "01J9"}).encode(),
        status,
        {"Idempotency-Replayed": "TRUE"},
    )
    assert failure.is_replayed
    assert failure.order_outcome is OrderRefusalOutcome.NOT_PLACED


def test_an_unreadable_problem_body_uses_the_internal_error_fallback() -> None:
    """Map a verified non-problem refusal without inventing an untrustworthy application code."""
    failure = create_api_error(b"<html>bad gateway</html>", 502, {})
    assert isinstance(failure, DependencyUnavailableError)
    assert failure.status == 502
    assert failure.order_outcome is OrderRefusalOutcome.UNKNOWN


def test_retry_after_and_replay_headers_are_preserved() -> None:
    """Keep signed refusal headers available so a host can resume after the instructed delay."""
    failure = create_api_error(
        b'{"code":"rate_limited","requestId":"req-1"}',
        429,
        {"retry-after": "17", "Idempotency-Replayed": "false"},
    )
    assert failure.retry_after == timedelta(seconds=17)
    assert failure.request_id == "req-1"
    assert failure.is_retryable
    assert ErrorCode.INTERNAL_ERROR in RETRYABLE_CODES


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("05", 5),
        ("00000000005", 5),
        ("0", 0),
        ("2147483647", 2_147_483_647),
        ("2147483648", None),
        ("+5", None),
        (" 5", None),
        ("\u0665", None),
    ],
)
def test_retry_after_accepts_decimal_seconds_by_value(value: str, expected: int | None) -> None:
    """Accept digit-only seconds by numeric value, including leading zeros, within signed 32-bit bounds."""
    delay = parse_retry_after(value)
    assert delay == (timedelta(seconds=expected) if expected is not None else None)
