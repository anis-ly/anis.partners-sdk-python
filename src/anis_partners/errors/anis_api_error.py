"""Partner-facing typed errors built from RFC 9457 answers, verified first on every signed route."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import timedelta
from enum import StrEnum

from anis_partners._internal.http_headers import has_true_value
from anis_partners.errors._codes import RETRYABLE_CODES, ErrorCode, parse_error_code
from anis_partners.errors.base import AnisPartnersError
from anis_partners.models.problem import Problem


class OrderRefusalOutcome(StrEnum):
    """Distinguish a closed refusal from an answer where the order may still have completed."""

    NOT_PLACED = "not_placed"
    UNKNOWN = "unknown"


def refused_at_the_door(code: ErrorCode) -> bool:
    """Identify access or signature refusals decided before lookup, when an earlier attempt may still be selling."""
    return code in {
        ErrorCode.INVALID_CREDENTIALS,
        ErrorCode.SIGNATURE_EXPIRED,
        ErrorCode.INSUFFICIENT_SCOPE,
        ErrorCode.WALLET_NOT_GRANTED,
        ErrorCode.MALFORMED_SIGNED_REQUEST,
    }


def outcome_of(code: ErrorCode) -> OrderRefusalOutcome:
    """Keep possibly accepted orders open so recovery uses the same operation id and cannot buy twice."""
    if code in {
        ErrorCode.DEPENDENCY_UNAVAILABLE,
        ErrorCode.REQUEST_TIMEOUT,
        ErrorCode.INTERNAL_ERROR,
        ErrorCode.OPERATION_PROCESSING,
        ErrorCode.REPLAY_DETECTED,
        ErrorCode.RATE_LIMITED,
        ErrorCode.UNKNOWN,
    } or refused_at_the_door(code):
        return OrderRefusalOutcome.UNKNOWN
    return OrderRefusalOutcome.NOT_PLACED


class AnisApiError(AnisPartnersError):
    """Carry machine-readable refusal data because titles and details are localized presentation."""

    def __init__(
        self,
        problem: Problem,
        status: int,
        retry_after: timedelta | None = None,
        is_replayed: bool = False,
    ) -> None:
        self.problem = problem
        self.code = parse_error_code(problem.code)
        self.raw_code = problem.code
        self.status = status
        self.request_id = problem.request_id
        self.type_uri = problem.type
        self.retry_after = retry_after
        self.is_replayed = is_replayed
        message = f"Anis returned {status} {problem.code}"
        if is_replayed:
            message += " (the recorded answer of an earlier attempt with this operation id)"
        if problem.request_id is not None:
            message += f" (request {problem.request_id})"
        super().__init__(message + ". Branch on the code, not on this message.")

    def __reduce__(self) -> tuple[object, tuple[object, ...]]:
        """Rebuild typed refusal data when callers copy, serialize, or journal the exception."""
        return (type(self), (self.problem, self.status, self.retry_after, self.is_replayed))

    @property
    def is_retryable(self) -> bool:
        """Report catalogue retryability only; unknown codes are never assumed retryable."""
        return self.code in RETRYABLE_CODES

    @property
    def order_outcome(self) -> OrderRefusalOutcome:
        """Treat recorded refusals as closed and use the code for fresh refusals."""
        return OrderRefusalOutcome.NOT_PLACED if self.is_replayed else outcome_of(self.code)


class MalformedResponseError(AnisPartnersError):
    """Report an answer body that does not fit its model without exposing its contents or parser details."""


class InsufficientBalanceError(AnisApiError):
    """A final balance refusal requires a top-up and a new operation identity."""


class PriceChangedError(AnisApiError):
    """A price refusal requires a fresh catalogue read and a new order intent."""


class OutOfStockError(AnisApiError):
    """Availability and quantity refusals are final until the catalogue changes."""


class IdempotencyConflictError(AnisApiError):
    """The operation id already belongs to a different order and must not be reused for that intent."""


class RateLimitedError(AnisApiError):
    """A rate limit may hide an earlier create, so orders resume with the same operation id."""


class LimitExceededError(AnisApiError):
    """An owner allowance is a final refusal until its authoritative limit changes."""


class InvalidCredentialsError(AnisApiError):
    """Credential refusals intentionally hide whether the key, signature, or application state failed."""


class ReplayDetectedError(AnisApiError):
    """An identical signed copy arrived first, so an order may already be underway."""


class AuthorizationError(AnisApiError):
    """Policy refusals need an access change rather than a blind retry."""


class ResourceNotFoundError(AnisApiError):
    """Missing and inaccessible resources share one result so access is not disclosed."""


class ValidationFailedError(AnisApiError):
    """Validation refusals do not identify fields, preventing resource and price probing."""


class DependencyUnavailableError(AnisApiError):
    """Anis could not reach a decision, so any related order must stay open for same-id recovery."""


class EnrollmentRefusedError(AnisApiError):
    """Represent an enrollment-step refusal without confusing it with a failed proof status."""


_ERROR_TYPES: dict[ErrorCode, type[AnisApiError]] = {
    ErrorCode.INSUFFICIENT_BALANCE: InsufficientBalanceError,
    ErrorCode.PRICE_CHANGED: PriceChangedError,
    ErrorCode.QUANTITY_UNAVAILABLE: OutOfStockError,
    ErrorCode.CARD_UNAVAILABLE: OutOfStockError,
    ErrorCode.IDEMPOTENCY_CONFLICT: IdempotencyConflictError,
    ErrorCode.RATE_LIMITED: RateLimitedError,
    ErrorCode.OWNER_LIMIT_EXCEEDED: LimitExceededError,
    ErrorCode.DAILY_LIMIT_EXCEEDED: LimitExceededError,
    ErrorCode.INVALID_CREDENTIALS: InvalidCredentialsError,
    ErrorCode.SIGNATURE_EXPIRED: InvalidCredentialsError,
    ErrorCode.REPLAY_DETECTED: ReplayDetectedError,
    ErrorCode.INSUFFICIENT_SCOPE: AuthorizationError,
    ErrorCode.SOURCE_IP_NOT_ALLOWED: AuthorizationError,
    ErrorCode.BINDING_NOT_AUTHORIZED: AuthorizationError,
    ErrorCode.ACCOUNT_INACTIVE: AuthorizationError,
    ErrorCode.BUSINESS_SUBSCRIPTION_REQUIRED: AuthorizationError,
    ErrorCode.WALLET_DISABLED: AuthorizationError,
    ErrorCode.WALLET_EXPIRED: AuthorizationError,
    ErrorCode.PURCHASE_NOT_ALLOWED: AuthorizationError,
    ErrorCode.REVEAL_NOT_ALLOWED: AuthorizationError,
    ErrorCode.RESOURCE_NOT_FOUND: ResourceNotFoundError,
    ErrorCode.CARD_NOT_FOUND: ResourceNotFoundError,
    ErrorCode.WALLET_NOT_GRANTED: ResourceNotFoundError,
    ErrorCode.VALIDATION_FAILED: ValidationFailedError,
    ErrorCode.CURRENCY_NOT_SUPPORTED: ValidationFailedError,
    ErrorCode.DEPENDENCY_UNAVAILABLE: DependencyUnavailableError,
    ErrorCode.REQUEST_TIMEOUT: DependencyUnavailableError,
    ErrorCode.INTERNAL_ERROR: DependencyUnavailableError,
    ErrorCode.INVITATION_INVALID: EnrollmentRefusedError,
    ErrorCode.CHALLENGE_EXPIRED: EnrollmentRefusedError,
    ErrorCode.KEY_PROOF_INVALID: EnrollmentRefusedError,
    ErrorCode.KEY_DUPLICATE: EnrollmentRefusedError,
}


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """Find semantic headers case-insensitively because HTTP field names ignore casing."""
    return next((value for key, value in headers.items() if key.lower() == name.lower()), None)


def create_api_error(body: bytes, status: int, headers: Mapping[str, str]) -> AnisApiError:
    """Map a refusal (verified when its route is signed), falling back to internal_error if its body is unreadable."""
    replayed = has_true_value(_header(headers, "Idempotency-Replayed"))
    retry_after_value = _header(headers, "Retry-After")
    retry_after = parse_retry_after(retry_after_value)
    try:
        problem = Problem.from_json(body)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        problem = Problem(type="about:blank", title="Unreadable problem", status=status, code="internal_error")
    error_type = _ERROR_TYPES.get(parse_error_code(problem.code), AnisApiError)
    return error_type(problem, status, retry_after, replayed)


def parse_retry_after(value: str | None) -> timedelta | None:
    """Accept bounded whole seconds so zero remains meaningful and huge values cannot overflow."""
    if value is None or not value.isascii() or not value.isdecimal():
        return None
    significant = value.lstrip("0") or "0"
    if len(significant) > 10:
        return None
    seconds = int(significant)
    return timedelta(seconds=seconds) if seconds <= 2_147_483_647 else None
