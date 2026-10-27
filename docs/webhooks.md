# Webhooks

Anis sends a notification to your HTTPS endpoint when a meter charge or a direct recharge changes. Verify every delivery before you read any of it. The SDK gives you the endpoint calls, the delivery list, and a verifier; it does not run a web server and has no web framework dependency.

## Set up the endpoint

```python
from anis_partners import SetWebhookEndpointRequest

endpoint = anis.webhook_endpoint.set(SetWebhookEndpointRequest("https://example.ly/hooks/anis"))
print(endpoint.status, endpoint.generation)  # pendingVerification until Anis completes the challenge
```

The URL must use HTTPS on port 443, with a host name that contains a dot, such as `hooks.example.com` (not an IP address, and not a single-label name like `localhost`), no user name or password, no fragment, and at most 2048 characters (`webhook_endpoint_invalid` otherwise). Setting the same URL again keeps its registration and state; a different URL starts verification again.

`endpoint.status` is `notConfigured`, `pendingVerification`, `verified` or `disabled`; `url` and `generation` are `None` until something is configured. A disabled endpoint stays disabled until Anis staff enable it. `webhook_endpoint.test()` asks Anis to send a test notification and returns the queued delivery; it needs a verified endpoint (`webhook_endpoint_unverified` otherwise). These calls need no permission scope.

### The verification challenge

After you set a URL, Anis sends a signed notification of type `webhook_endpoint.verification` whose data holds a random `challenge` and the registration `generation`. Verify it like any delivery, then answer with a 2xx within 10 seconds and exactly this JSON body, with no other members:

```json
{"challenge": "<the same value>"}
```

Never echo a challenge from a request you have not verified.

Anis calls your endpoint from one fixed address per deployment. If your firewall only accepts known sources, allow the
address listed in [Where webhooks come from](https://developers.anis.ly/docs/webhooks#where-webhooks-come-from); the signature, not the address, proves a request came from Anis.

## Verify before you read

Capture the raw request bytes before any JSON middleware parses them: the signature covers those exact bytes, so a re-serialized body is refused. Build a `VerifiableWebhook` from the method, the absolute URL you served, the headers and the raw body, and give the verifier your own configured URL and application id. The trusted public origin comes from configuration; the path and query must come from the observed request target without decoding or normalization. Compare that raw target with the registered target, and configure your trusted proxy to preserve it. Never substitute the configured full URL for the received URL or use forwarding headers to choose the origin.

```python
import httpx

from anis_partners import (
    HttpSigningKeySource,
    PartnerWebhookVerifier,
    UnverifiableWebhookError,
    VerifiableWebhook,
)

keys = HttpSigningKeySource(httpx.Client(), "https://<authority Anis gave you>")
verifier = PartnerWebhookVerifier(
    keys,
    configured_url="https://example.ly/hooks/anis",  # exactly as registered, including any query
    application_id="<your application id>",
)


def receive(method: str, url: str, headers: dict[str, str], raw_body: bytes) -> int:
    try:
        envelope = verifier.verify_and_parse(VerifiableWebhook(method, url, headers, raw_body))
    except UnverifiableWebhookError as refusal:
        logger.warning("Refused a notification", extra={"reason": refusal.failure.value})
        return 401
    database.record_and_handle(envelope)  # atomically handle and deduplicate, or retain a durable pending entry
    return 200
```

`verify_and_parse` returns the typed envelope only after the signature, URL, application and event id all check out. `verify` checks without parsing. `AsyncPartnerWebhookVerifier` takes an `AsyncSigningKeySource` and awaits the same checks. The pure function `verify_webhook(webhook, keys, now, configured_url=…, application_id=…)` returns the first failure without any key-document request.

Anis publishes the notification keys in the same signing-key document as the answer keys, marked with `purpose` `webhook`. The verifier accepts only an exact key id with that purpose whose status is `active` or `next` and whose activation time has passed. A retired key is refused even for a signature created before its retirement, and a compromised key is refused whatever the signing date. An unknown key id refreshes the key document at most once per 30 seconds, like response verification.

Each signature lives 300 seconds. The verifier refuses a different lifetime, a signature past its expiry (no grace), and a creation time more than 300 seconds from your clock; keep your clock accurate.

### Refusal reasons

`UnverifiableWebhookError.failure` is a `WebhookVerificationFailure` with a stable value: `signature_missing`, `signature_malformed`, `signature_invalid`, `content_digest_mismatch`, `covered_components_mismatch`, `unknown_key`, `key_rejected`, `algorithm_not_supported`, `label_unexpected`, `created_out_of_window`, `profile_unexpected`, `key_compromised`, `key_retired`, `key_not_yet_valid`, `signature_expired`, `validity_window_invalid`, `target_uri_mismatch`, `application_id_mismatch`, `key_purpose_mismatch`, `method_unexpected`, `event_id_mismatch` and `envelope_invalid`. Most are trust failures of the delivery itself; `event_id_mismatch`, `application_id_mismatch` (when the signed body names another application) and `envelope_invalid` describe a correctly signed delivery that is not usable. The error text carries no body or key data. Do not log the raw body, the signature or the signature base.

## What a notification contains

The envelope is `id`, `type`, `occurredAt`, `applicationId` and `data`. `data` is the current read of the operation: a `MeterCharge` for `meterCharge.succeeded` and `meterCharge.failed`, and a `DirectRecharge` for `directRecharge.paid`, `.paymentFailed`, `.suspended`, `.completed`, `.rejected` and `.partiallyRefunded`. The type says what triggered the notification; act on the verified `data.status`. A `directRecharge.suspended` notification delivered after you corrected the recipient may legitimately carry `inProgress`.

An unknown future type is accepted once verified: `envelope.type` is `WebhookEventType.UNKNOWN`, `envelope.raw_type` keeps the wire value and `envelope.data` keeps the object. Do not treat it as a completed result.

### Deduplicate on the event id

Anis delivers at least once and retries failures for about three days. The same event keeps the same `id` on every attempt and on redelivery; the attempt number is not an identity. Deduplicate on `id` in your own database, after verification and before you act or acknowledge. The SDK keeps no dedupe state of its own.

Commit the business changes and the handled marker in one database transaction. Alternatively, persist a verified envelope as pending before handling it, retain it on failure, and recover pending work after a restart. Return a non-2xx when handling fails. External effects must be idempotent on the event id or use a transactional outbox; a process can stop after the external effect but before recording success.

The [receiver sample](../samples/console/webhook_receiver.py) stores verified envelopes in a SQLite inbox, returns 503 on handling failure, and recovers pending entries on startup. It marks an event handled only after the handler succeeds. Its sample action prints safe metadata; replace that action with your idempotent business handler. Keep the inbox private: it contains meter tokens and recipient data.

## Follow and repeat deliveries

```python
from anis_partners import WebhookDeliveryStatus, WebhookEventsQuery

for event in anis.webhook_events.get_webhook_events(WebhookEventsQuery(status=WebhookDeliveryStatus.FAILED)):
    print(event.id, event.type, event.attempts, event.last_failure_kind)
```

`get_webhook_events` follows every page (50 per page) and keeps your `status` and `since` filter; use `get_webhook_events_page` to manage the cursor yourself. The list shows delivery state only, never recipient data or tokens. `webhook_events.redeliver(event_id)` asks Anis to send the same event again and returns the queued delivery; it needs a verified endpoint.

The endpoint change, test and redeliver calls are signed changes without an idempotency key. The SDK does not repeat them after a failure: read the endpoint or the delivery list first, then decide.
