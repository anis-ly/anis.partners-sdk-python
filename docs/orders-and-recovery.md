# Orders and recovery

An order can spend money and release card codes. Store and commit the operation id and exact request before the call so a timeout or process restart can be recovered safely. Recovery is a signed `POST` through `orders.resume()`; never run a `GET` loop to retry a purchase. Do not put an automatic retry layer around the SDK's HTTP client: it would resend the same nonce and can be refused as a replay. Call `resume()` to create a fresh signature and nonce for the same operation id and body.

## The operation id belongs to your application

```python
from uuid import uuid4

operation_id = uuid4()
database.record_order_intent(operation_id, wallet_id, request)  # before sending
outcome = anis.orders.create(wallet_id=wallet_id, operation_id=operation_id, order=request)
```

The operation id becomes the `Idempotency-Key` and identifies one purchase across Anis. The SDK does not create it for you: generating a fresh id after a lost answer could place a second order. Store the same id and unchanged body in your database before sending. In an async application, use `AsyncAnisPartnersClient` and await both the persistence calls and SDK calls inside your async flow.

## Send the wallet price exactly

Read the card from the selected wallet's catalogue. `unit_price` is the price that wallet pays and the price checked by Anis; display prices may differ. A card without a wallet price cannot be sold to that wallet.

```python
from anis_partners import CreateOrderRequest

unit_price = card.unit_price
if unit_price is None:
    raise ValueError("This card is not priced for the selected wallet.")

request = CreateOrderRequest(
    card.id,
    quantity=2,
    expected_unit_price=unit_price,
    expected_total=unit_price.multiply(2),  # exact Decimal arithmetic
    external_reference="your-order-123",
)
```

Money on the wire has exactly three decimal places and uppercase three-letter currency codes; a wallet balance is negative (for example `-150.000`) while the wallet uses allowed debt, and prices and totals are never negative. Python Decimal constructors accept up to three decimal places and pad shorter scales without rounding. The SDK checks positive unit price, quantity, currency, and `unit × quantity` before sending. `external_reference`, when supplied, is limited by the API to 100 characters and its accepted character set. `use_allowed_debt` defaults to false; set it to true only when the buyer has explicitly agreed to use allowed debt.

## The five results

Import the result variants you match below. The store, support, reveal, scheduling, and close functions are
application-owned callbacks; persist the operation intent before calling the SDK.

```python
from anis_partners import (
    OrderCompleted,
    OrderNotPlaced,
    OrderOutcomeUnknown,
    OrderProcessing,
    OrderReplayed,
)

if isinstance(outcome, OrderCompleted) and outcome.credentials:
    credential_store.save(outcome.credentials)  # store supplied codes before choosing a recovery branch

match outcome:
    case OrderCompleted(codes_withheld=True):
        alert_support(operation_id)  # paid, no codes were released; do not buy again
    case OrderCompleted():
        mark_fulfillment_ready(operation_id)
    case OrderReplayed(order=prior):
        reveal_from_invoice(prior.invoice_id)  # a replay does not carry codes
    case OrderProcessing(retry_after=delay):
        schedule_resume(operation_id, delay)
    case OrderOutcomeUnknown(suggested_delay=delay):
        schedule_resume(operation_id, delay)  # same id, same request
    case OrderNotPlaced(refusal=refusal):
        close_without_charge(operation_id, refusal)  # fix the cause; a new intent gets a new id
```

| Result | Meaning | Safe next action |
|---|---|---|
| `OrderCompleted` | A new completion, or a recovered completion. Credentials are returned only on the first completion response. `codes_withheld` reports a completed order with no codes. | Store credentials securely before reporting success. Never repeat the purchase. |
| `OrderProcessing` | Anis accepted the order and is still processing it. | Wait `retry_after`, then resume. |
| `OrderReplayed` | The same id already completed; Anis returned the prior result without credentials. | Use an authorized reveal if codes are needed again. |
| `OrderOutcomeUnknown` | No answer, an unverifiable answer, an uncertain refusal, an access refusal, or a fresh refusal during resume. The original order may have completed. | Resume with the same id and exact request. Never create a replacement id to retry it. |
| `OrderNotPlaced` | A definitive refusal closed the order. | Fix the cause, then use a new id only for a new attempt. |

A spending-cap refusal (`spending_limit_exceeded`, HTTP 429, `LimitExceededError`) is `OrderNotPlaced`: the order would have taken the application or wallet past its spending cap for the current window, so nothing was bought or charged. `retry_after` is the time until the window ends (windows follow UTC). After it, place a new order with a new id; never resume the refused one.

`RECOVERY EXHAUSTED` means Anis still cannot establish the final result. It is not a failed order. Keep the original id and body, wait several minutes before resuming again, and contact [support@anis.ly](mailto:support@anis.ly) with the operation id if recovery remains exhausted. Never create a replacement id while the outcome may be unknown. A completed result may also state that codes were withheld; record the successful order and use the authorized reveal flow if needed instead of ordering again.

The sync and async clients raise `ValueError` or `TypeError` directly for invalid caller arguments, including malformed ids, a missing order, or invalid quantity and price arithmetic. These checks happen before a request is built or sent. Once those arguments are valid, a request-signing failure such as a signer or serialization problem raises `RequestSigningError` before send and is never an unknown order result. A transport timeout, connection failure, or discarded answer after handoff is `OrderOutcomeUnknown`.

## Meter charges and direct recharges

A meter charge (`meter_charges.create`) and a direct recharge (`direct_recharges.create`) spend money exactly like an order and follow the same rules. Your application owns the operation id and the unchanged request: record both before the call, and recover with `resume` using the same id, wallet and request. Resuming sends a fresh signature and nonce for identical bytes; it never makes a new purchase.

```python
from anis_partners import (
    CreateMeterChargeRequest,
    MeterChargeFinal,
    MeterChargeNotPlaced,
    MeterChargeOutcomeUnknown,
    MeterChargeProcessing,
)


def charge(charge_request: CreateMeterChargeRequest) -> None:
    database.record_meter_intent(operation_id, wallet_id, charge_request)  # before sending
    result = anis.meter_charges.create(wallet_id=wallet_id, operation_id=operation_id, request=charge_request)
    match result:
        case MeterChargeFinal(charge=done):
            database.record_meter_result(operation_id, done)  # succeeded, or failed with its refund decided
        case MeterChargeProcessing(retry_after=delay):
            schedule_resume(operation_id, delay)  # still working: resume or read later
        case MeterChargeOutcomeUnknown(suggested_delay=delay):
            schedule_resume(operation_id, delay)  # same id, same request
        case MeterChargeNotPlaced(refusal=refusal):
            close_without_charge(operation_id, refusal)
```

`DirectRechargeResult` has the same four cases (`DirectRechargeFinal`, `DirectRechargeProcessing`, `DirectRechargeNotPlaced`, `DirectRechargeOutcomeUnknown`).

- **Processing.** Anis accepted the request and answers with only the operation id, its type and `processing`. Wait the suggested delay, then resume or read the operation. A direct recharge that is paid, pending, in progress, paused or waiting for a refund is still in progress; only a final status closes it.
- **Final.** A succeeded charge, a failed charge whose refund is decided (`refunded` or `notCharged`), or a completed, payment-failed or rejected-with-refund direct recharge. A failed charge with a decided refund is a final result, not a refusal and not an exception. A partial refund alone does not complete a direct recharge. A failed charge whose refund is still `pending` is not final: the money was taken and the refund is on its way, so it is reported as processing with the read attached. Read again or wait for the `meterCharge.failed` webhook.
- **Not placed.** A definitive refusal on the first call, or a recorded refusal returned again. Fix the cause and use a new id only for a new attempt. `idempotency_conflict` is never reported as not placed (see Unknown).
- **Unknown.** A timeout, a lost or unreadable answer, an answer whose signature cannot be verified, or an answer about a different operation. The original may have been placed: resume with the same id. A refusal that is not a recorded replay stays unknown when you resume. `idempotency_conflict` on a create or a resume is always unknown: the operation may already have been accepted and charged, so read the operation by its id with `get` before any new attempt.

Reading with `meter_charges.get` and `direct_recharges.get` returns the full signed read once Anis has recorded the operation. Before that it returns the three-member processing answer (`MeterChargeAccepted` / `DirectRechargeAccepted`), which never carries receipt, price or recipient fields. The two shapes are separate models; do not treat the missing members of a processing answer as zero or empty.

When the operation was closed with a recorded refusal (a signed 409 or 422 sent with `Idempotency-Replayed: true`), `get` raises the typed API error for that code instead of returning a read. `raw_code` carries the code and `is_replayed` is `True`. That is the definitive answer for that id, including for `idempotency_conflict`.

If the retried id was never recorded and Anis cannot prove it belongs to you, it answers processing for up to 60 seconds and then closes the operation as failed with `idempotency_conflict`. The SDK reports that verified answer as an unknown outcome, because the operation may already have been accepted and charged, and never creates a replacement id. Read the operation by its id with `get`: for an id that is not yours the read answers not found, and for a closed conflict it raises the recorded refusal.

Correcting a recipient (`update_recipient`), setting or testing the webhook endpoint and requesting redelivery are signed changes, not purchases. They carry no idempotency key and the SDK never retries them: after a failure, read the direct recharge, endpoint or delivery list first and then decide whether to send the change again.

A successful recipient correction returns `DirectRechargeProcessing`, the same result type as a 202 direct recharge create. Its `recharge` holds a `DirectRechargeAccepted` acknowledgement with exactly `operationId`, `operationType: directRecharge` and `status: processing`. The result’s `location` holds the signed `Location` response header for `GET /v1/direct-recharges/{operationId}`; it remains separate from the acknowledgement JSON. `retry_after` uses the same response-header mapping as creates. No direct recharge body is returned. This applies to both sync and async clients.

```python
from anis_partners import UpdateDirectRechargeRecipientRequest

acknowledgement = anis.direct_recharges.update_recipient(
    operation_id, UpdateDirectRechargeRecipientRequest(request.recipient)
)
print(acknowledgement.recharge.to_json(), acknowledgement.location)
```

Read `direct_recharges.get(acknowledgement.operation_id)` later or wait for a verified `directRecharge.*` webhook. An immediate GET can still show the old `suspendedDataError` state while the read side catches up. Never automatically repeat the PATCH after a 202 or a lost answer: an already-applied correction can be refused as `direct_recharge_not_suspended`.

## Resume the saved intent

```python
intent = database.read_order_intent(operation_id)
outcome = anis.orders.resume(wallet_id=intent.wallet_id, operation_id=intent.operation_id, order=intent.request)
```

`resume` sends the original body under the original operation id with a fresh signature and nonce. Do not rebuild the body using a new price, quantity, or external reference. A refusal during resume can describe the new call rather than the earlier purchase; it is therefore unknown unless Anis marks it as the recorded replayed refusal.

For a completed replay that no longer includes credentials, the order contains its invoice id. Revealing again uses the explicit `cards:reveal` permission and is subject to the invoice reveal limit. Persist the recovered outcome and credentials in your protected store before marking fulfillment complete.
