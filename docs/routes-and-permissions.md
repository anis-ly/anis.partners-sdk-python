# Routes and permissions

The table lists the route, Python operation, required permission, request signature style, whether the answer is signed, body, and request limit bucket. The SDK selects the signing profile and body shape.

Every partner request is signed, on every partner route; enrollment requests carry the enrollment token instead because no key exists yet, and the public key document needs neither. Anis signs only the answers that move money, deliver card codes, change the webhook endpoint or establish a key, plus the signature self-test. On those routes every answer — the success and each refusal — is signed and the SDK verifies it; one without a signature is refused with `UnverifiableResponseError` (`signature_missing`). The other routes answer without `Signature` or `Signature-Input` (`Content-Digest` and `X-Request-Id` are still present), and the SDK reads those answers without verification. The choice is fixed per route in `PARTNER_ROUTES` (`PartnerRoute.signs_response`); the SDK never decides from the answer whether to verify it.

| Python call | Route | Permission | Request signed as | Answer | Body | Counts toward |
|---|---|---|---|---|---|---|
| `access.suspend_application(reason)` | `POST /v1/application/suspend` | no scope required | nonce mutation | signed, verified | `{"reason":"…"}` | requests |
| `access.revoke_key(key_id, reason)` | `POST /v1/keys/{keyId}/revoke` | no scope required | nonce mutation | signed, verified | `{"reason":"…"}` | requests |
| `catalogue.get_card(wallet_id, card_id)` | `GET /v1/wallets/{walletId}/catalog/cards/{cardId}` | `catalogue:read` | safe read | unsigned, not verified | none | requests |
| `profile.get()` | `GET /v1/profile` | `profile:read` | safe read | unsigned, not verified | none | requests |
| `wallets.list()` / `list_page()` | `GET /v1/wallets` | `wallets:read` | safe read | unsigned, not verified | none | requests |
| `wallets.get(wallet_id)` | `GET /v1/wallets/{walletId}` | `wallets:read` | safe read | unsigned, not verified | none | requests |
| `catalogue.list_categories()` / `list_categories_page()` | `GET /v1/wallets/{walletId}/catalog/categories` | `catalogue:read` | safe read | unsigned, not verified | none | requests |
| `catalogue.list_subcategories()` / `list_subcategories_page()` | `GET /v1/wallets/{walletId}/catalog/categories/{categoryId}/subcategories` | `catalogue:read` | safe read | unsigned, not verified | none | requests |
| `catalogue.get_subcategory()` | `GET /v1/wallets/{walletId}/catalog/subcategories/{subcategoryId}` | `catalogue:read` | safe read | unsigned, not verified | none | requests |
| `catalogue.list_cards()` / `list_cards_page()` | `GET /v1/wallets/{walletId}/catalog/subcategories/{subcategoryId}/cards` | `catalogue:read` | safe read | unsigned, not verified | none | requests |
| `orders.create()` / `resume()` | `POST /v1/wallets/{walletId}/orders` | `orders:create` | order | signed, verified | order JSON | requests, orders |
| `orders.get()` | `GET /v1/orders/{operationId}` | `orders:read`, or `orders:create` for this application's own orders | safe read | signed, verified | none | requests |
| `owned_cards.list()` / `list_page()` | `GET /v1/wallets/{walletId}/owned-cards` | `cards:read` | safe read | unsigned, not verified | none | requests |
| `owned_cards.get()` | `GET /v1/wallets/{walletId}/owned-cards/{soldCardId}` | `cards:read` | safe read | unsigned, not verified | none | requests |
| `owned_cards.reveal()` | `POST /v1/wallets/{walletId}/owned-cards/{soldCardId}/reveal` | `cards:reveal` | nonce mutation | signed, verified | zero bytes | requests, reveals |
| `owned_cards.reveal_invoice()` | `POST /v1/wallets/{walletId}/invoices/{invoiceId}/owned-cards/reveal` | `cards:reveal` | nonce mutation | signed, verified | zero bytes | requests, reveals |
| `meter_charges.get_meter_packages()` / `get_meter_packages_page()` | `GET /v1/wallets/{walletId}/meter-packages` | `meter_charges:read` | safe read | unsigned, not verified | none | requests |
| `meter_charges.get_meter_charges()` / `get_meter_charges_page()` | `GET /v1/wallets/{walletId}/meter-charges` | `meter_charges:read` | safe read | unsigned, not verified | none | requests |
| `meter_charges.create()` / `resume()` | `POST /v1/wallets/{walletId}/meter-charges` | `meter_charges:create` | order | signed, verified | charge JSON | requests, orders |
| `meter_charges.get()` | `GET /v1/meter-charges/{operationId}` | `meter_charges:read` | safe read | signed, verified | none | requests |
| `direct_recharge_products.get_direct_recharge_products()` / `…_page()` | `GET /v1/wallets/{walletId}/direct-recharge-products` | `direct_recharges:read` | safe read | unsigned, not verified | none | requests |
| `direct_recharge_products.get()` | `GET /v1/wallets/{walletId}/direct-recharge-products/{productId}` | `direct_recharges:read` | safe read | unsigned, not verified | none | requests |
| `direct_recharge_products.get_direct_recharge_product_locations()` / `…_page()` | `GET /v1/wallets/{walletId}/direct-recharge-products/{productId}/locations` | `direct_recharges:read` | safe read | unsigned, not verified | none | requests |
| `direct_recharge_products.quote()` | `GET /v1/wallets/{walletId}/direct-recharge-products/{productId}/quote` | `direct_recharges:read` | safe read | unsigned, not verified | none | requests |
| `direct_recharges.get_direct_recharges()` / `get_direct_recharges_page()` | `GET /v1/wallets/{walletId}/direct-recharges` | `direct_recharges:read` | safe read | unsigned, not verified | none | requests |
| `direct_recharges.create()` / `resume()` | `POST /v1/wallets/{walletId}/direct-recharges` | `direct_recharges:create` | order | signed, verified | direct recharge JSON | requests, orders |
| `direct_recharges.get()` | `GET /v1/direct-recharges/{operationId}` | `direct_recharges:read` | safe read | signed, verified | none | requests |
| `direct_recharges.update_recipient()` | `PATCH /v1/direct-recharges/{operationId}/recipient` | `direct_recharges:create` | nonce mutation | signed, verified | recipient JSON | requests |
| `webhook_endpoint.get()` | `GET /v1/webhook-endpoint` | no scope required | safe read | unsigned, not verified | none | requests |
| `webhook_endpoint.set()` | `PUT /v1/webhook-endpoint` | no scope required | nonce mutation | signed, verified | `{"url":"…"}` | requests |
| `webhook_endpoint.test()` | `POST /v1/webhook-endpoint/test` | no scope required | nonce mutation | signed, verified | exactly `{}` | requests |
| `webhook_events.get_webhook_events()` / `get_webhook_events_page()` | `GET /v1/webhook-events` | no scope required | safe read | unsigned, not verified | none | requests |
| `webhook_events.redeliver()` | `POST /v1/webhook-events/{eventId}/redeliver` | no scope required | nonce mutation | signed, verified | exactly `{}` | requests |
| `diagnostics.check_signature()` | `POST /v1/diagnostics/signature` | `diagnostics:use` | nonce mutation | signed, verified | exactly `{}` | requests |
| `AnisEnrollmentClient.get()` | `GET /v1/enrollments/{invitationId}` | enrollment token | unsigned | signed, verified | none | — |
| `AnisEnrollmentClient.submit_key()` | `POST /v1/enrollments/{invitationId}/keys` | enrollment token | unsigned | signed, verified | public key | — |
| `AnisEnrollmentClient.submit_proof()` / `prove()` | `POST /v1/enrollments/{invitationId}/proof` | enrollment token | unsigned | signed, verified | proof | — |
| `AnisEnrollmentClient.get_status()` | `GET /v1/enrollments/{invitationId}/status` | enrollment token | unsigned | signed, verified | none | — |
| Key retrieval | `GET /.well-known/partner-signing-keys.json` | public | unsigned | unsigned, not verified | none | — |

Meter charges and direct recharges are separate products with their own permissions. `meter_charges:create` and `direct_recharges:create` each include the matching read permission (packages, charges, products, locations, quotes and direct recharge reads), but a read permission never allows a create. The webhook routes need no permission; they need only an admitted application and network. The operation reads, the recipient correction and every webhook route act on your own application, so they take no wallet id. Query strings (filters, `pageSize`, `cursor`, `since`) are not part of a route template.

Creating a meter charge or a direct recharge counts against the same `orders` request limit and the same daily spending cap as card orders; there is no separate allowance per product.

The `list()` methods follow every cursor page. Use the matching `list_*_page()` method when the application manages cursors itself. Pass each cursor back exactly as received. The new collection methods are named `get_<things>()` for the iterator and `get_<things>_page()` for one page; they keep your filters on every page.

The two reveal routes send no body, though the empty body digest is signed. The signature diagnostic sends `{}`. A proxy or middleware that adds a body or changes signed headers can cause refusal.

An address outside the network agreed with Anis and a missing permission may share the same `insufficient_scope` response. A missing or inaccessible resource may also share a response. This keeps the answer from revealing access policy.

Catalogue `minimumQuantity` is always 1; `maximumQuantity` is the platform order limit (100).

Direct recharge product reads, locations and quotes take `product_id` in both sync and async clients. For example, use `anis.direct_recharge_products.get(wallet_id=wallet_id, product_id=product_id)`. Limits and recipient labels can be absent; keep them as `None` rather than inventing a limit or label. Empty recipient values stay empty strings in create, correction and saved recovery intent.

The balance check for a direct recharge is exact for wallet balances up to 999,999.999 LYD. The SDK keeps public monetary values as decimal strings.

Recipient correction returns a signed 202 acknowledgement, exposed as `DirectRechargeProcessing`, the same result type as a 202 direct recharge create. Its `recharge` is a `DirectRechargeAccepted` acknowledgement and `location` comes from the signed `Location` header. It never returns a direct recharge body. Use the operation GET later or wait for its verified webhook; the SDK never automatically repeats the PATCH.
