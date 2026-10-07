# Routes and permissions

The table lists the route, Python operation, required permission, request signature style, whether the answer is signed, body, and request limit bucket. The SDK selects the signing profile and body shape.

Every partner request is signed, on every partner route; enrollment requests carry the enrollment token instead because no key exists yet, and the public key document needs neither. Anis signs only the answers that move money, deliver card codes, or establish a key, plus the signature self-test. On those routes every answer — the success and each refusal — is signed and the SDK verifies it; one without a signature is refused with `UnverifiableResponseError` (`signature_missing`). The other routes answer without `Signature` or `Signature-Input` (`Content-Digest` and `X-Request-Id` are still present), and the SDK reads those answers without verification. The choice is fixed per route in `PARTNER_ROUTES` (`PartnerRoute.signs_response`); the SDK never decides from the answer whether to verify it.

| Python call | Route | Permission | Request signed as | Answer | Body | Counts toward |
|---|---|---|---|---|---|---|
| `profile.get()` | `GET /v1/profile` | `profile:read` | safe read | unsigned, not verified | none | requests |
| `wallets.list()` / `list_page()` | `GET /v1/wallets` | `wallets:read` | safe read | unsigned, not verified | none | requests |
| `wallets.get(wallet_id)` | `GET /v1/wallets/{walletId}` | `wallets:read` | safe read | unsigned, not verified | none | requests |
| `catalogue.list_categories()` / `list_categories_page()` | `GET /v1/wallets/{walletId}/catalog/categories` | `catalogue:read` | safe read | unsigned, not verified | none | requests |
| `catalogue.list_subcategories()` / `list_subcategories_page()` | `GET /v1/wallets/{walletId}/catalog/categories/{categoryId}/subcategories` | `catalogue:read` | safe read | unsigned, not verified | none | requests |
| `catalogue.get_subcategory()` | `GET /v1/wallets/{walletId}/catalog/subcategories/{subcategoryId}` | `catalogue:read` | safe read | unsigned, not verified | none | requests |
| `catalogue.list_cards()` / `list_cards_page()` | `GET /v1/wallets/{walletId}/catalog/subcategories/{subcategoryId}/cards` | `catalogue:read` | safe read | unsigned, not verified | none | requests |
| `orders.create()` / `resume()` | `POST /v1/wallets/{walletId}/orders` | `orders:create` | order | signed, verified | order JSON | requests, orders |
| `orders.get()` | `GET /v1/orders/{operationId}` | `orders:read`, or `orders:create` for this application's own orders | safe read | signed, verified | none | requests |
| `owned_cards.list()` / `list_page()` | `GET /v1/wallets/{walletId}/cards` | `cards:read` | safe read | unsigned, not verified | none | requests |
| `owned_cards.get()` | `GET /v1/wallets/{walletId}/cards/{soldCardId}` | `cards:read` | safe read | unsigned, not verified | none | requests |
| `owned_cards.reveal()` | `POST /v1/wallets/{walletId}/cards/{soldCardId}/reveal` | `cards:reveal` | nonce mutation | signed, verified | zero bytes | requests, reveals |
| `owned_cards.reveal_invoice()` | `POST /v1/wallets/{walletId}/invoices/{invoiceId}/cards/reveal` | `cards:reveal` | nonce mutation | signed, verified | zero bytes | requests, reveals |
| `diagnostics.check_signature()` | `POST /v1/diagnostics/signature` | `diagnostics:use` | nonce mutation | signed, verified | exactly `{}` | requests |
| `AnisEnrollmentClient.get()` | `GET /v1/enrollments/{invitationId}` | enrollment token | unsigned | signed, verified | none | — |
| `AnisEnrollmentClient.submit_key()` | `POST /v1/enrollments/{invitationId}/keys` | enrollment token | unsigned | signed, verified | public key | — |
| `AnisEnrollmentClient.submit_proof()` / `prove()` | `POST /v1/enrollments/{invitationId}/proof` | enrollment token | unsigned | signed, verified | proof | — |
| `AnisEnrollmentClient.get_status()` | `GET /v1/enrollments/{invitationId}/status` | enrollment token | unsigned | signed, verified | none | — |
| Key retrieval | `GET /.well-known/partner-signing-keys.json` | public | unsigned | unsigned, not verified | none | — |

The `list()` methods follow every cursor page. Use the matching `list_*_page()` method when the application manages cursors itself. Pass each cursor back exactly as received.

The two reveal routes send no body, though the empty body digest is signed. The signature diagnostic sends `{}`. A proxy or middleware that adds a body or changes signed headers can cause refusal.

An address outside the network agreed with Anis and a missing permission may share the same `insufficient_scope` response. A missing or inaccessible resource may also share a response. This keeps the answer from revealing access policy.
