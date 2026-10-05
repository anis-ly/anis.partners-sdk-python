# Observability

The SDK uses the OpenTelemetry API, not an OpenTelemetry implementation. Add an SDK/exporter in your application when you want to export signals. Instrumentation uses the scope `anis_partners`; logging uses the `anis_partners` logger and structured `event_id` extras.

## Traces

Each request creates a client span named `anis.partners {route}` with span kind `CLIENT`. Attributes include:

| Attribute | Meaning |
|---|---|
| `anis.client` | Logical client name (`default` unless configured internally) |
| `anis.route` | Route template, without concrete resource ids |
| `http.request.method` | HTTP method |
| `anis.operation_id` | Caller-supplied order id, for order requests |
| `http.response.status_code` | Verified response status |
| `error.type` | Safe category such as `timeout`, `connection`, `signing`, or `unverifiable` |
| `anis.error.code` | Stable code from a verified API refusal |

## Metrics

| Instrument | Measurements and attributes |
|---|---|
| `anis.partners.request.duration` histogram (`ms`) | `anis.client`, route template, method, and safe result or error category; verified responses include request id when present |
| `anis.partners.signature.duration` histogram (`ms`) | `anis.signature.profile` |
| `anis.partners.response.verification.failures` counter | `anis.verification.failure` |
| `anis.partners.order.outcomes` counter | `anis.client`, outcome; unknown outcomes may include `error.type` |
| `anis.partners.signing_keys.fetches` counter | `anis.fetch.reason` (`first-use`, `expired`, or `refresh`) |

## Logs

Events use the `anis_partners` logger and put the stable numeric event id in `extra["event_id"]`. Events cover request completion (`1001`), verified refusals (`1002`), discarded responses (`1003`), order results (`1004`, `1008`), fetched signing keys (`1005`), key refresh after an unknown id (`1006`), and unanswered requests (`1007`). Request completion and refusal records include route, method, status, request id, and stable error code where available.

The SDK does not log request or response bodies, signature bytes or bases, nonces, authorization values, enrollment tokens, vouchers, serial numbers, or card codes. Hosts should preserve that boundary in their own logging and tracing.
