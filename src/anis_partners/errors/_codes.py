"""GENERATED from contracts/error-catalogue.json; do not edit, run tools/generate_errors.py."""

from enum import StrEnum


class ErrorCode(StrEnum):
    """Identify API refusals by stable wire code rather than localized copy."""

    UNKNOWN = "unknown"
    ACCOUNT_INACTIVE = "account_inactive"
    ALLOWED_DEBT_CONSENT_REQUIRED = "allowed_debt_consent_required"
    BINDING_NOT_AUTHORIZED = "binding_not_authorized"
    BUSINESS_SUBSCRIPTION_REQUIRED = "business_subscription_required"
    CARD_NOT_FOUND = "card_not_found"
    CARD_UNAVAILABLE = "card_unavailable"
    CHALLENGE_EXPIRED = "challenge_expired"
    CURRENCY_NOT_SUPPORTED = "currency_not_supported"
    DAILY_LIMIT_EXCEEDED = "daily_limit_exceeded"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    INSUFFICIENT_SCOPE = "insufficient_scope"
    INTERNAL_ERROR = "internal_error"
    INVALID_CONTENT_DIGEST = "invalid_content_digest"
    INVALID_CREDENTIALS = "invalid_credentials"
    INVITATION_INVALID = "invitation_invalid"
    INVOICE_REVEAL_LIMIT_EXCEEDED = "invoice_reveal_limit_exceeded"
    KEY_DUPLICATE = "key_duplicate"
    KEY_PROOF_INVALID = "key_proof_invalid"
    MALFORMED_SIGNED_REQUEST = "malformed_signed_request"
    OPERATION_PROCESSING = "operation_processing"
    OWNER_LIMIT_EXCEEDED = "owner_limit_exceeded"
    PRICE_CHANGED = "price_changed"
    PURCHASE_NOT_ALLOWED = "purchase_not_allowed"
    QUANTITY_UNAVAILABLE = "quantity_unavailable"
    RATE_LIMITED = "rate_limited"
    REPLAY_DETECTED = "replay_detected"
    REQUEST_TIMEOUT = "request_timeout"
    RESOURCE_NOT_FOUND = "resource_not_found"
    REVEAL_NOT_ALLOWED = "reveal_not_allowed"
    SIGNATURE_EXPIRED = "signature_expired"
    SOURCE_IP_NOT_ALLOWED = "source_ip_not_allowed"
    VALIDATION_FAILED = "validation_failed"
    WALLET_DISABLED = "wallet_disabled"
    WALLET_EXPIRED = "wallet_expired"
    WALLET_NOT_GRANTED = "wallet_not_granted"


RETRYABLE_CODES: frozenset[ErrorCode] = frozenset(
    {
        ErrorCode.DEPENDENCY_UNAVAILABLE,
        ErrorCode.INTERNAL_ERROR,
        ErrorCode.OPERATION_PROCESSING,
        ErrorCode.RATE_LIMITED,
        ErrorCode.REPLAY_DETECTED,
        ErrorCode.REQUEST_TIMEOUT,
        ErrorCode.SIGNATURE_EXPIRED,
    }
)


_BY_WIRE: dict[str, ErrorCode] = {
    "account_inactive": ErrorCode.ACCOUNT_INACTIVE,
    "allowed_debt_consent_required": ErrorCode.ALLOWED_DEBT_CONSENT_REQUIRED,
    "binding_not_authorized": ErrorCode.BINDING_NOT_AUTHORIZED,
    "business_subscription_required": ErrorCode.BUSINESS_SUBSCRIPTION_REQUIRED,
    "card_not_found": ErrorCode.CARD_NOT_FOUND,
    "card_unavailable": ErrorCode.CARD_UNAVAILABLE,
    "challenge_expired": ErrorCode.CHALLENGE_EXPIRED,
    "currency_not_supported": ErrorCode.CURRENCY_NOT_SUPPORTED,
    "daily_limit_exceeded": ErrorCode.DAILY_LIMIT_EXCEEDED,
    "dependency_unavailable": ErrorCode.DEPENDENCY_UNAVAILABLE,
    "idempotency_conflict": ErrorCode.IDEMPOTENCY_CONFLICT,
    "insufficient_balance": ErrorCode.INSUFFICIENT_BALANCE,
    "insufficient_scope": ErrorCode.INSUFFICIENT_SCOPE,
    "internal_error": ErrorCode.INTERNAL_ERROR,
    "invalid_content_digest": ErrorCode.INVALID_CONTENT_DIGEST,
    "invalid_credentials": ErrorCode.INVALID_CREDENTIALS,
    "invitation_invalid": ErrorCode.INVITATION_INVALID,
    "invoice_reveal_limit_exceeded": ErrorCode.INVOICE_REVEAL_LIMIT_EXCEEDED,
    "key_duplicate": ErrorCode.KEY_DUPLICATE,
    "key_proof_invalid": ErrorCode.KEY_PROOF_INVALID,
    "malformed_signed_request": ErrorCode.MALFORMED_SIGNED_REQUEST,
    "operation_processing": ErrorCode.OPERATION_PROCESSING,
    "owner_limit_exceeded": ErrorCode.OWNER_LIMIT_EXCEEDED,
    "price_changed": ErrorCode.PRICE_CHANGED,
    "purchase_not_allowed": ErrorCode.PURCHASE_NOT_ALLOWED,
    "quantity_unavailable": ErrorCode.QUANTITY_UNAVAILABLE,
    "rate_limited": ErrorCode.RATE_LIMITED,
    "replay_detected": ErrorCode.REPLAY_DETECTED,
    "request_timeout": ErrorCode.REQUEST_TIMEOUT,
    "resource_not_found": ErrorCode.RESOURCE_NOT_FOUND,
    "reveal_not_allowed": ErrorCode.REVEAL_NOT_ALLOWED,
    "signature_expired": ErrorCode.SIGNATURE_EXPIRED,
    "source_ip_not_allowed": ErrorCode.SOURCE_IP_NOT_ALLOWED,
    "validation_failed": ErrorCode.VALIDATION_FAILED,
    "wallet_disabled": ErrorCode.WALLET_DISABLED,
    "wallet_expired": ErrorCode.WALLET_EXPIRED,
    "wallet_not_granted": ErrorCode.WALLET_NOT_GRANTED,
}


def parse_error_code(raw_code: str | None) -> ErrorCode:
    """Map an unknown future code safely so it is never assumed retryable."""
    return _BY_WIRE.get(raw_code, ErrorCode.UNKNOWN) if raw_code is not None else ErrorCode.UNKNOWN
