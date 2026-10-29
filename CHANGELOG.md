# Changelog

## [Unreleased]

### Added

- `CreateDirectRechargeRequest.contact_phone`: an optional phone the Anis exchanges team calls about the direct recharge (a Libyan mobile or an international number). When omitted, Anis uses the phone saved for the partner. It is part of the request's idempotency: the same `Idempotency-Key` with a different value is an `idempotency_conflict`. Hidden from `repr`.

## [2.2.0] - 2026-10-27

### Added

- Charge electricity meters and read receipts, tokens and refunds with safe recovery after an interrupted request.
- Quote direct recharges, follow them and correct recipient details while a direct recharge is paused.
- Manage a webhook endpoint and request delivery again when a notification was missed.
- Verify notifications before reading their contents and keep recipient field errors available to the integration.

### Changed

- `idempotency_conflict` on a meter charge or direct recharge create or resume is now an unknown outcome (`MeterChargeOutcomeUnknown` / `DirectRechargeOutcomeUnknown`), not "not placed": the operation may already have been accepted and charged, so read it by its id with `get` before any new attempt. Card orders are unchanged.
- A meter charge read as `failed` with a `pending` refund is reported as processing, not final: the money was taken and the refund is on its way.
- Reading a meter charge or direct recharge that was closed with a recorded refusal raises the typed API error with `is_replayed` set.
- A webhook endpoint URL must have a host name that contains a dot.

### Security

- A key published for webhooks can no longer verify an API answer; a key without a purpose still verifies, as before.

## [2.1.0] - 2026-10-18

### Added

- Catalogue subcategories expose `category_type` (`categoryType`) with local and international values, and unknown when absent or unrecognized.
- Catalogue card `category` exposes `type` with the same values and unknown handling. Owned cards, reveals and orders are unchanged.

## [2.0.1] - 2026-10-13

### Fixed

- A wallet whose balance is below zero — while it uses allowed debt — can be read again. In 2.0.0, listing or reading such a wallet failed with an error. Amounts in Anis's answers may carry a leading minus sign (`-150.000`); `-0.000` reads as zero. `Money` accepts a negative `Decimal` too.
- Prices you send are unchanged: an order still refuses a unit price that is not greater than zero, before anything is sent.
- Documentation: the spending-cap refusal (`spending_limit_exceeded`) and the money rule in Orders and recovery; the live-verification note now says which version it covers.

## [2.0.0] - 2026-10-13

### Breaking changes

- Recognise `spending_limit_exceeded` (HTTP 429): a spending-capped order is not placed and is reported as `LimitExceededError` with the `Retry-After` delay until the spending window ends.
- Require `anis-response-v2`, bind the raw request signature, and enforce compromised and retired signing-key state. Every published response key (active, next or retired) refuses a signature created before its `notBefore` (`key_not_yet_valid`).
- The signing-key document is cached for 300 seconds by default and at most 300 seconds; `ClientOptions` and both key sources refuse a longer cache.
- An unknown response key id re-fetches the key document at most once per 30 seconds per key source (sync and async), failed fetches included.
- Documentation: retired keys stay published for 90 days after retirement.
- Use `/owned-cards` routes and shared `CardSummary` in masked cards, reveals and order credentials; masked ids are `sold_card_id` and `operation_id`. Wallet currency is `balance.currency`. Money wire values require nonnegative three-place amounts and uppercase currency codes.
- Add `access.suspend_application(reason)`, `access.revoke_key(key_id, reason)`, and `catalogue.get_card(wallet_id, card_id)` in both clients. Catalogue cards include logo/category and subcategory lists include description.

1.x is deprecated — upgrade to 2.0.0.

## [1.1.0] - 2026-10-07

Anis now signs only the answers that move money, deliver card codes, or establish a key: orders (create and read), the two reveals, the four enrollment routes, and the signature self-test. On those routes every answer, success or refusal, is still verified, and an answer with no signature is still refused (`signature_missing`). The information reads — profile, wallets, the four catalogue reads, and the owned-card list and read — now come back unsigned, and the SDK reads them without verification, so they keep working while a signing-key fetch fails. Which routes are signed is fixed per route in `PARTNER_ROUTES` (`PartnerRoute.signs_response`), never inferred from the answer. Requests are signed exactly as before. Telemetry scope version is now `1.1.0`.

## [1.0.0] - 2026-10-06

First release of `anis-partners`. Partners get signed requests, verified responses, typed models and errors, synchronous and asynchronous operation groups, enrollment support, safe order recovery outcomes, bounded signing-key caching, and tests against the published wire vectors and contracts.
