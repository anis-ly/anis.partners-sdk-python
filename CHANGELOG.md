# Changelog

## [2.0.0] - 2026-10-11

### Breaking changes

- Require `anis-response-v2`, bind the raw request signature, and enforce compromised, retired and next signing-key state.
- Use `/owned-cards` routes and shared `CardSummary` in masked cards, reveals and order credentials; masked ids are `sold_card_id` and `operation_id`. Wallet currency is `balance.currency`. Money wire values require nonnegative three-place amounts and uppercase currency codes.
- Add `access.suspend_application(reason)`, `access.revoke_key(key_id, reason)`, and `catalogue.get_card(wallet_id, card_id)` in both clients. Catalogue cards include logo/category and subcategory lists include description.

1.x is deprecated — upgrade to 2.0.0.

## [1.1.0] - 2026-10-07

Anis now signs only the answers that move money, deliver card codes, or establish a key: orders (create and read), the two reveals, the four enrollment routes, and the signature self-test. On those routes every answer, success or refusal, is still verified, and an answer with no signature is still refused (`signature_missing`). The information reads — profile, wallets, the four catalogue reads, and the owned-card list and read — now come back unsigned, and the SDK reads them without verification, so they keep working while a signing-key fetch fails. Which routes are signed is fixed per route in `PARTNER_ROUTES` (`PartnerRoute.signs_response`), never inferred from the answer. Requests are signed exactly as before. Telemetry scope version is now `1.1.0`.

## [1.0.0] - 2026-10-06

First release of `anis-partners`. Partners get signed requests, verified responses, typed models and errors, synchronous and asynchronous operation groups, enrollment support, safe order recovery outcomes, bounded signing-key caching, and tests against the published wire vectors and contracts.
