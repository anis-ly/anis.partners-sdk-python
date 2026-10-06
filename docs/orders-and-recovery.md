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

Prices accept up to three decimal places and never round longer values. The SDK checks positive unit price, quantity, currency, and `unit × quantity` before sending. `external_reference`, when supplied, is limited by the API to 100 characters and its accepted character set. `use_allowed_debt` defaults to false; set it to true only when the buyer has explicitly agreed to use allowed debt.

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

`RECOVERY EXHAUSTED` means Anis still cannot establish the final result. It is not a failed order. Keep the original id and body, wait several minutes before resuming again, and contact [support@anis.ly](mailto:support@anis.ly) with the operation id if recovery remains exhausted. Never create a replacement id while the outcome may be unknown. A completed result may also state that codes were withheld; record the successful order and use the authorized reveal flow if needed instead of ordering again.

The sync and async clients raise `ValueError` or `TypeError` directly for invalid caller arguments, including malformed ids, a missing order, or invalid quantity and price arithmetic. These checks happen before a request is built or sent. Once those arguments are valid, a request-signing failure such as a signer or serialization problem raises `RequestSigningError` before send and is never an unknown order result. A transport timeout, connection failure, or discarded answer after handoff is `OrderOutcomeUnknown`.

## Resume the saved intent

```python
intent = database.read_order_intent(operation_id)
outcome = anis.orders.resume(wallet_id=intent.wallet_id, operation_id=intent.operation_id, order=intent.request)
```

`resume` sends the original body under the original operation id with a fresh signature and nonce. Do not rebuild the body using a new price, quantity, or external reference. A refusal during resume can describe the new call rather than the earlier purchase; it is therefore unknown unless Anis marks it as the recorded replayed refusal.

For a completed replay that no longer includes credentials, the order contains its invoice id. Revealing again uses the explicit `cards:reveal` permission and is subject to the invoice reveal limit. Persist the recovered outcome and credentials in your protected store before marking fulfillment complete.
