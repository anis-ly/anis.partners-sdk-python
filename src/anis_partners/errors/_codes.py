"""GENERATED from contracts/error-catalogue.json; do not edit, run tools/generate_errors.py."""

from enum import StrEnum


class ErrorCode(StrEnum):
    """Identify API refusals by stable wire code and recovery guidance."""

    UNKNOWN = "unknown"
    ACCOUNT_INACTIVE = "account_inactive"
    ALLOWED_DEBT_CONSENT_REQUIRED = "allowed_debt_consent_required"
    AMOUNT_OUT_OF_RANGE = "amount_out_of_range"
    BINDING_NOT_AUTHORIZED = "binding_not_authorized"
    BUSINESS_SUBSCRIPTION_REQUIRED = "business_subscription_required"
    CARD_NOT_FOUND = "card_not_found"
    CARD_UNAVAILABLE = "card_unavailable"
    CHALLENGE_EXPIRED = "challenge_expired"
    CURRENCY_NOT_SUPPORTED = "currency_not_supported"
    DAILY_LIMIT_EXCEEDED = "daily_limit_exceeded"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    DIRECT_RECHARGE_NOT_SUSPENDED = "direct_recharge_not_suspended"
    DIRECT_RECHARGE_PRODUCT_UNAVAILABLE = "direct_recharge_product_unavailable"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    INSUFFICIENT_SCOPE = "insufficient_scope"
    INTERNAL_ERROR = "internal_error"
    INVALID_CONTENT_DIGEST = "invalid_content_digest"
    INVALID_CREDENTIALS = "invalid_credentials"
    INVITATION_INVALID = "invitation_invalid"
    INVOICE_REVEAL_LIMIT_EXCEEDED = "invoice_reveal_limit_exceeded"
    KEY_DUPLICATE = "key_duplicate"
    KEY_NOT_REVOCABLE = "key_not_revocable"
    KEY_PROOF_INVALID = "key_proof_invalid"
    MALFORMED_SIGNED_REQUEST = "malformed_signed_request"
    METER_REJECTED = "meter_rejected"
    NETWORK_NOT_REMOVABLE = "network_not_removable"
    OPERATION_PROCESSING = "operation_processing"
    OWNER_LIMIT_EXCEEDED = "owner_limit_exceeded"
    PACKAGE_UNAVAILABLE = "package_unavailable"
    PARTNER_NETWORK_LIMIT_REACHED = "partner_network_limit_reached"
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
    SPENDING_LIMIT_EXCEEDED = "spending_limit_exceeded"
    VALIDATION_FAILED = "validation_failed"
    WALLET_DISABLED = "wallet_disabled"
    WALLET_EXPIRED = "wallet_expired"
    WALLET_NOT_GRANTED = "wallet_not_granted"
    WEBHOOK_ENDPOINT_INVALID = "webhook_endpoint_invalid"
    WEBHOOK_ENDPOINT_UNVERIFIED = "webhook_endpoint_unverified"


HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.ACCOUNT_INACTIVE: 403,
    ErrorCode.ALLOWED_DEBT_CONSENT_REQUIRED: 402,
    ErrorCode.AMOUNT_OUT_OF_RANGE: 422,
    ErrorCode.BINDING_NOT_AUTHORIZED: 403,
    ErrorCode.BUSINESS_SUBSCRIPTION_REQUIRED: 409,
    ErrorCode.CARD_NOT_FOUND: 404,
    ErrorCode.CARD_UNAVAILABLE: 409,
    ErrorCode.CHALLENGE_EXPIRED: 409,
    ErrorCode.CURRENCY_NOT_SUPPORTED: 422,
    ErrorCode.DAILY_LIMIT_EXCEEDED: 429,
    ErrorCode.DEPENDENCY_UNAVAILABLE: 503,
    ErrorCode.DIRECT_RECHARGE_NOT_SUSPENDED: 409,
    ErrorCode.DIRECT_RECHARGE_PRODUCT_UNAVAILABLE: 409,
    ErrorCode.IDEMPOTENCY_CONFLICT: 409,
    ErrorCode.INSUFFICIENT_BALANCE: 409,
    ErrorCode.INSUFFICIENT_SCOPE: 403,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.INVALID_CONTENT_DIGEST: 400,
    ErrorCode.INVALID_CREDENTIALS: 401,
    ErrorCode.INVITATION_INVALID: 401,
    ErrorCode.INVOICE_REVEAL_LIMIT_EXCEEDED: 409,
    ErrorCode.KEY_DUPLICATE: 409,
    ErrorCode.KEY_NOT_REVOCABLE: 409,
    ErrorCode.KEY_PROOF_INVALID: 422,
    ErrorCode.MALFORMED_SIGNED_REQUEST: 400,
    ErrorCode.METER_REJECTED: 422,
    ErrorCode.NETWORK_NOT_REMOVABLE: 409,
    ErrorCode.OPERATION_PROCESSING: 202,
    ErrorCode.OWNER_LIMIT_EXCEEDED: 409,
    ErrorCode.PACKAGE_UNAVAILABLE: 409,
    ErrorCode.PARTNER_NETWORK_LIMIT_REACHED: 409,
    ErrorCode.PRICE_CHANGED: 409,
    ErrorCode.PURCHASE_NOT_ALLOWED: 409,
    ErrorCode.QUANTITY_UNAVAILABLE: 409,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.REPLAY_DETECTED: 409,
    ErrorCode.REQUEST_TIMEOUT: 504,
    ErrorCode.RESOURCE_NOT_FOUND: 404,
    ErrorCode.REVEAL_NOT_ALLOWED: 409,
    ErrorCode.SIGNATURE_EXPIRED: 401,
    ErrorCode.SOURCE_IP_NOT_ALLOWED: 403,
    ErrorCode.SPENDING_LIMIT_EXCEEDED: 429,
    ErrorCode.VALIDATION_FAILED: 422,
    ErrorCode.WALLET_DISABLED: 409,
    ErrorCode.WALLET_EXPIRED: 409,
    ErrorCode.WALLET_NOT_GRANTED: 404,
    ErrorCode.WEBHOOK_ENDPOINT_INVALID: 422,
    ErrorCode.WEBHOOK_ENDPOINT_UNVERIFIED: 409,
}


RETRY_GUIDANCE: dict[ErrorCode, str] = {
    ErrorCode.ACCOUNT_INACTIVE: "Confirm or re-enable the owner account before making a new request.",
    ErrorCode.ALLOWED_DEBT_CONSENT_REQUIRED: "".join(
        (
            "Submit a new operation with explicit allowed-debt ",
            "consent if the Partner intends to use debt.",
        )
    ),
    ErrorCode.AMOUNT_OUT_OF_RANGE: "Choose an amount within the quoted limits.",
    ErrorCode.BINDING_NOT_AUTHORIZED: "".join(
        (
            "Restore the directly owned active account and Busi",
            "ness subscription before making a new request.",
        )
    ),
    ErrorCode.BUSINESS_SUBSCRIPTION_REQUIRED: "Restore an active Business subscription before making a new request.",
    ErrorCode.CARD_NOT_FOUND: "".join(
        (
            "Verify the sold-card identifier and wallet; absent",
            " and inaccessible single cards return the same rep",
            "resentation.",
        )
    ),
    ErrorCode.CARD_UNAVAILABLE: "Refresh Catalogue data and submit a new operation if the item becomes available.",
    ErrorCode.CHALLENGE_EXPIRED: "".join(
        (
            "Restart enrollment through the approved staff acti",
            "on and use the new challenge generation.",
        )
    ),
    ErrorCode.CURRENCY_NOT_SUPPORTED: "Use the currency required by the authoritative wallet and Catalogue contract.",
    ErrorCode.DAILY_LIMIT_EXCEEDED: "".join(
        (
            "No reset time is available; submit a new operation",
            " and idempotency key only after the limit conditio",
            "n is known to have cleared.",
        )
    ),
    ErrorCode.DEPENDENCY_UNAVAILABLE: "".join(
        (
            "Retry with the same idempotency key for the same m",
            "utation intent after bounded backoff.",
        )
    ),
    ErrorCode.DIRECT_RECHARGE_NOT_SUSPENDED: "Read the direct recharge; recipient changes require suspendedDataError.",
    ErrorCode.DIRECT_RECHARGE_PRODUCT_UNAVAILABLE: "Choose an available transfer priced for this wallet tier.",
    ErrorCode.IDEMPOTENCY_CONFLICT: "".join(
        (
            "Reuse the key only for identical intent. This code",
            " does not say the original request failed: it may ",
            "already have been accepted and charged, so never a",
            "ssume nothing was charged; read the original opera",
            "tion by its id (the meter charge or the direct rec",
            "harge) before any new attempt. A repeated create w",
            "hose id is still unknown to this application a min",
            "ute after it was admitted also closes as idempoten",
            "cy_conflict (409); use a new UUID only for a genui",
            "nely new operation.",
        )
    ),
    ErrorCode.INSUFFICIENT_BALANCE: "".join(
        (
            "Submit a new operation only after the authoritativ",
            "e balance or allowed-debt state changes.",
        )
    ),
    ErrorCode.INSUFFICIENT_SCOPE: "".join(
        (
            "The application is not permitted to make this call",
            ": check that it holds the permission the call need",
            "s and that you call from a network agreed with Ani",
            "s, then ask Anis staff to change either.",
        )
    ),
    ErrorCode.INTERNAL_ERROR: "".join(
        (
            "Preserve the same accepted operation and idempoten",
            "cy key; retry only after bounded backoff or platfo",
            "rm remediation.",
        )
    ),
    ErrorCode.INVALID_CONTENT_DIGEST: "".join(
        (
            "Reserved: the current API never sends this code. A",
            " Content-Digest that does not match the body is an",
            "swered malformed_signed_request (400).",
        )
    ),
    ErrorCode.INVALID_CREDENTIALS: "".join(
        (
            "Correct the signing credentials or profile before ",
            "retrying; key and application state details are in",
            "tentionally indistinguishable.",
        )
    ),
    ErrorCode.INVITATION_INVALID: "Obtain a new enrollment invitation through the approved staff process.",
    ErrorCode.INVOICE_REVEAL_LIMIT_EXCEEDED: "".join(
        (
            "Use individual reveal for selected cards; invoice ",
            "reveal is capped at 100.",
        )
    ),
    ErrorCode.KEY_DUPLICATE: "".join(
        (
            "This invitation already took a key, so a newly gen",
            "erated key pair is refused too. Read the enrolment",
            " status first; to enrol a different key, ask Anis ",
            "staff to restart the enrolment.",
        )
    ),
    ErrorCode.KEY_NOT_REVOCABLE: "A retired key cannot be revoked. Use the current application credential.",
    ErrorCode.KEY_PROOF_INVALID: "Correct the P-256/P1363 proof for the active challenge generation.",
    ErrorCode.MALFORMED_SIGNED_REQUEST: "".join(
        (
            "Rebuild how the request is signed: send both Signa",
            "ture and Signature-Input, cover the required compo",
            "nents in the documented order, send every header t",
            "he route requires, and compute Content-Digest over",
            " the exact body bytes. Repeating the same request ",
            "unchanged fails the same way.",
        )
    ),
    ErrorCode.METER_REJECTED: "Correct the meter number and use a new Idempotency-Key for a new attempt.",
    ErrorCode.NETWORK_NOT_REMOVABLE: "".join(
        (
            "Anis added this network, so only Anis can remove i",
            "t, or it is the last network the application has. ",
            "Contact Anis support to change it.",
        )
    ),
    ErrorCode.OPERATION_PROCESSING: "".join(
        (
            "Not an error: the operation is still processing. R",
            "espect Retry-After; read its Location or repeat th",
            "e identical create with the same Idempotency-Key.",
        )
    ),
    ErrorCode.OWNER_LIMIT_EXCEEDED: "".join(
        (
            "Do not poll; submit a new operation and idempotenc",
            "y key only after the owner allowance is known to h",
            "ave changed.",
        )
    ),
    ErrorCode.PACKAGE_UNAVAILABLE: "Choose an available package and use a new Idempotency-Key.",
    ErrorCode.PARTNER_NETWORK_LIMIT_REACHED: "".join(
        (
            "The application already has the most addresses a P",
            "artner may add. Remove one you added, or ask Anis ",
            "to allow the network.",
        )
    ),
    ErrorCode.PRICE_CHANGED: "Refresh the current price and explicitly accept it in a new operation.",
    ErrorCode.PURCHASE_NOT_ALLOWED: "".join(
        (
            "The request conflicts with current owner business ",
            "state; submit a new operation only after that stat",
            "e changes.",
        )
    ),
    ErrorCode.QUANTITY_UNAVAILABLE: "Refresh Catalogue data or submit a new operation with an available quantity.",
    ErrorCode.RATE_LIMITED: "honour Retry-After when present; otherwise use bounded exponential backoff.",
    ErrorCode.REPLAY_DETECTED: "".join(
        (
            "Use a fresh nonce and signature while preserving t",
            "he idempotency key for the same business intent.",
        )
    ),
    ErrorCode.REQUEST_TIMEOUT: "".join(
        (
            "Inspect operation status or repeat the identical r",
            "equest with the same idempotency key.",
        )
    ),
    ErrorCode.RESOURCE_NOT_FOUND: "".join(
        (
            "Verify the resource identifier and application own",
            "ership; inaccessible resources are intentionally i",
            "ndistinguishable from absence.",
        )
    ),
    ErrorCode.REVEAL_NOT_ALLOWED: "".join(
        (
            "The card-level reveal predicate refused disclosure",
            "; do not retry until the card state is known to ha",
            "ve changed.",
        )
    ),
    ErrorCode.SIGNATURE_EXPIRED: "".join(
        (
            "Reserved: the current API never sends this code. A",
            " signature outside its validity window is answered",
            " invalid_credentials (401); sign again with curren",
            "t timestamps.",
        )
    ),
    ErrorCode.SOURCE_IP_NOT_ALLOWED: "".join(
        (
            "Anis network protection blocked this source addres",
            "s. Contact Anis support with the address if it sho",
            "uld be allowed.",
        )
    ),
    ErrorCode.SPENDING_LIMIT_EXCEEDED: "".join(
        (
            "The operation was not accepted: it would take the ",
            "application's spending above its ceiling for the c",
            "urrent period. Do not repeat it; after the Retry-A",
            "fter delay (the end of the period) submit a new op",
            "eration and idempotency key, or ask Anis staff to ",
            "change the ceiling.",
        )
    ),
    ErrorCode.VALIDATION_FAILED: "".join(
        (
            "Check the request model and framing. Money-operati",
            "on creates and recipient updates accept at most 81",
            "92 UTF-8 body bytes. Recipient validation of a dir",
            "ect recharge may return safe messages in extension",
            "s.fields; other validation does not identify field",
            "s. Preserve the same key for unchanged accepted in",
            "tent; a corrected business intent needs a new key.",
        )
    ),
    ErrorCode.WALLET_DISABLED: "Submit a new request only after the wallet has been re-enabled.",
    ErrorCode.WALLET_EXPIRED: "".join(
        (
            "Submit a new request only after the account or Bus",
            "iness subscription expiry is resolved.",
        )
    ),
    ErrorCode.WALLET_NOT_GRANTED: "Obtain an approved current wallet grant before making a new request.",
    ErrorCode.WEBHOOK_ENDPOINT_INVALID: "".join(
        (
            "Use HTTPS on port 443 with a host name, no user-in",
            "fo or fragment, and at most 2048 characters.",
        )
    ),
    ErrorCode.WEBHOOK_ENDPOINT_UNVERIFIED: "".join(
        (
            "Set an endpoint and complete its verification befo",
            "re testing or redelivering.",
        )
    ),
}


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
    "amount_out_of_range": ErrorCode.AMOUNT_OUT_OF_RANGE,
    "binding_not_authorized": ErrorCode.BINDING_NOT_AUTHORIZED,
    "business_subscription_required": ErrorCode.BUSINESS_SUBSCRIPTION_REQUIRED,
    "card_not_found": ErrorCode.CARD_NOT_FOUND,
    "card_unavailable": ErrorCode.CARD_UNAVAILABLE,
    "challenge_expired": ErrorCode.CHALLENGE_EXPIRED,
    "currency_not_supported": ErrorCode.CURRENCY_NOT_SUPPORTED,
    "daily_limit_exceeded": ErrorCode.DAILY_LIMIT_EXCEEDED,
    "dependency_unavailable": ErrorCode.DEPENDENCY_UNAVAILABLE,
    "direct_recharge_not_suspended": ErrorCode.DIRECT_RECHARGE_NOT_SUSPENDED,
    "direct_recharge_product_unavailable": ErrorCode.DIRECT_RECHARGE_PRODUCT_UNAVAILABLE,
    "idempotency_conflict": ErrorCode.IDEMPOTENCY_CONFLICT,
    "insufficient_balance": ErrorCode.INSUFFICIENT_BALANCE,
    "insufficient_scope": ErrorCode.INSUFFICIENT_SCOPE,
    "internal_error": ErrorCode.INTERNAL_ERROR,
    "invalid_content_digest": ErrorCode.INVALID_CONTENT_DIGEST,
    "invalid_credentials": ErrorCode.INVALID_CREDENTIALS,
    "invitation_invalid": ErrorCode.INVITATION_INVALID,
    "invoice_reveal_limit_exceeded": ErrorCode.INVOICE_REVEAL_LIMIT_EXCEEDED,
    "key_duplicate": ErrorCode.KEY_DUPLICATE,
    "key_not_revocable": ErrorCode.KEY_NOT_REVOCABLE,
    "key_proof_invalid": ErrorCode.KEY_PROOF_INVALID,
    "malformed_signed_request": ErrorCode.MALFORMED_SIGNED_REQUEST,
    "meter_rejected": ErrorCode.METER_REJECTED,
    "network_not_removable": ErrorCode.NETWORK_NOT_REMOVABLE,
    "operation_processing": ErrorCode.OPERATION_PROCESSING,
    "owner_limit_exceeded": ErrorCode.OWNER_LIMIT_EXCEEDED,
    "package_unavailable": ErrorCode.PACKAGE_UNAVAILABLE,
    "partner_network_limit_reached": ErrorCode.PARTNER_NETWORK_LIMIT_REACHED,
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
    "spending_limit_exceeded": ErrorCode.SPENDING_LIMIT_EXCEEDED,
    "validation_failed": ErrorCode.VALIDATION_FAILED,
    "wallet_disabled": ErrorCode.WALLET_DISABLED,
    "wallet_expired": ErrorCode.WALLET_EXPIRED,
    "wallet_not_granted": ErrorCode.WALLET_NOT_GRANTED,
    "webhook_endpoint_invalid": ErrorCode.WEBHOOK_ENDPOINT_INVALID,
    "webhook_endpoint_unverified": ErrorCode.WEBHOOK_ENDPOINT_UNVERIFIED,
}


def parse_error_code(raw_code: str | None) -> ErrorCode:
    """Map an unknown future code safely so it is never assumed retryable."""
    return _BY_WIRE.get(raw_code, ErrorCode.UNKNOWN) if raw_code is not None else ErrorCode.UNKNOWN
