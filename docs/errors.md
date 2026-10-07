# Errors

## Branch on the code, not the message

For a read, catch `AnisApiError` and use its stable `code` or `raw_code`. The title and detail are localized presentation and can change with language or copy edits. `request_id` is the value to share with Anis support.

```python
from anis_partners import AnisApiError

try:
    profile = anis.profile.get()
except AnisApiError as failure:
    logger.warning(
        "Anis refused a request",
        extra={
            "code": failure.raw_code,
            "status": failure.status,
            "request_id": failure.request_id,
            "retryable": failure.is_retryable,
            "replayed": failure.is_replayed,
        },
    )
```

The error exposes `code` (the known `ErrorCode`, or `UNKNOWN`), `raw_code` (the wire spelling), `status`, `request_id`, `retry_after`, `is_retryable`, `is_replayed`, and `order_outcome`. Unknown codes are never considered retryable. Error messages do not replace those fields.

Order refusals are values, not thrown API exceptions: a closed refusal is in `OrderNotPlaced.refusal`; an uncertain refusal is the `cause` of `OrderOutcomeUnknown`. Read refusals raise their typed exception. A recorded refusal with the replay marker is closed and returns `OrderNotPlaced`.

## Error catalogue

The SDK's `ErrorCode` values come from `contracts/error-catalogue.json`; the table below describes their public mapping. `Retryable` describes a code and does not authorize a fresh order attempt. “May have placed” means an order must be resumed with the same operation id.

| Code | HTTP | Typed error | Retryable | Order may have placed? |
|---|---:|---|:---:|:---:|
| `account_inactive` | 403 | `AuthorizationError` | no | no |
| `allowed_debt_consent_required` | 402 | `AnisApiError` | no | no |
| `binding_not_authorized` | 403 | `AuthorizationError` | no | no |
| `business_subscription_required` | 409 | `AuthorizationError` | no | no |
| `card_not_found` | 404 | `ResourceNotFoundError` | no | no |
| `card_unavailable` | 409 | `OutOfStockError` | no | no |
| `challenge_expired` | 409 | `EnrollmentRefusedError` | no | no |
| `currency_not_supported` | 422 | `ValidationFailedError` | no | no |
| `daily_limit_exceeded` | 429 | `LimitExceededError` | no | no |
| `dependency_unavailable` | 503 | `DependencyUnavailableError` | yes | yes |
| `idempotency_conflict` | 409 | `IdempotencyConflictError` | no | no |
| `insufficient_balance` | 409 | `InsufficientBalanceError` | no | no |
| `insufficient_scope` | 403 | `AuthorizationError` | no | yes |
| `internal_error` | 500 | `DependencyUnavailableError` | yes | yes |
| `invalid_content_digest` | 400 | `AnisApiError` | no | no |
| `invalid_credentials` | 401 | `InvalidCredentialsError` | no | yes |
| `invitation_invalid` | 401 | `EnrollmentRefusedError` | no | no |
| `invoice_reveal_limit_exceeded` | 409 | `AnisApiError` | no | no |
| `key_duplicate` | 409 | `EnrollmentRefusedError` | no | no |
| `key_proof_invalid` | 422 | `EnrollmentRefusedError` | no | no |
| `malformed_signed_request` | 400 | `AnisApiError` | no | yes |
| `operation_processing` | 202 | `OrderProcessing` result, not an exception | yes | yes |
| `owner_limit_exceeded` | 409 | `LimitExceededError` | no | no |
| `price_changed` | 409 | `PriceChangedError` | no | no |
| `purchase_not_allowed` | 403 / 409 | `AuthorizationError` | no | no |
| `quantity_unavailable` | 409 | `OutOfStockError` | no | no |
| `rate_limited` | 429 | `RateLimitedError` | yes | yes |
| `replay_detected` | 409 | `ReplayDetectedError` | yes | yes |
| `request_timeout` | 504 | `DependencyUnavailableError` | yes | yes |
| `resource_not_found` | 404 | `ResourceNotFoundError` | no | no |
| `reveal_not_allowed` | 409 | `AuthorizationError` | no | no |
| `signature_expired` | 401 | `InvalidCredentialsError` | yes | yes |
| `source_ip_not_allowed` | 403 | `AuthorizationError` | no | no |
| `validation_failed` | 422 | `ValidationFailedError` | no | no |
| `wallet_disabled` | 409 | `AuthorizationError` | no | no |
| `wallet_expired` | 409 | `AuthorizationError` | no | no |
| `wallet_not_granted` | 404 | `ResourceNotFoundError` | no | yes |
| unknown code | varies | `AnisApiError` | no | yes |

The SDK also raises `EnrollmentKeyMismatchError` when the key thumbprint Anis returns differs from the submitted key. It is a local integrity error, not an API refusal.

Catch `AnisPartnersError` to handle errors raised by the SDK itself. API refusals derive from it as `AnisApiError`; `RequestSigningError`, `UnverifiableResponseError`, `EnrollmentKeyMismatchError`, `KeyDocumentUnavailableError`, and `MalformedResponseError` do too. A malformed answer reports only the response model name: its body and JSON parser detail may contain card codes or other private values. Send the route, operation id where relevant, and verified request id to [support@anis.ly](mailto:support@anis.ly); never send card codes, tokens, or private keys.

Invalid caller arguments raise `ValueError` or `TypeError` directly. For example, invalid UUID arguments name their Python parameter, and invalid order quantity or price arithmetic identifies `quantity`, `expected_unit_price`, or `expected_total`. `RequestSigningError` is reserved for request preparation failures after arguments pass validation, such as signer failures or serialization problems; neither kind is an unknown order outcome.

## Unverifiable answers are discarded

`UnverifiableResponseError` is raised only on a signed route (orders, reveals, enrollment, and the signature self-test); the information reads are answered unsigned and are not verified. `UnverifiableResponseError.failure` identifies why a response could not be trusted; an answer on a signed route with no signature is `signature_missing`. The SDK discards its body before parsing. This is different from an API refusal: a refusal is an answer from Anis (verified, on a signed route); an unverifiable answer has no trusted business meaning. For an order, the outcome is unknown and must be recovered using the same id. For a read, fix the cause and retry the read.

## Retryable codes do not mean new order ids

A read may be retried according to its error. An order with an unknown result must be resumed under the same operation id and exact body. Unknown future codes are not considered retryable. See [Orders and recovery](orders-and-recovery.md).

`validation_failed` intentionally does not identify the failing field. Check the published request contract, exact three-place decimal limit, UUIDs, and body rules before trying again.
