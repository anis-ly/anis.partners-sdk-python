# Routes and permissions

The table lists the route, Python operation, required permission, signature style, body, and request limit bucket. The SDK selects the signing profile and body shape.

| Python call | Route | Permission | Signed as | Body | Counts toward |
|---|---|---|---|---|---|
| `profile.get()` | `GET /v1/profile` | `profile:read` | safe read | none | requests |
| `wallets.list()` / `list_page()` | `GET /v1/wallets` | `wallets:read` | safe read | none | requests |
| `wallets.get(wallet_id)` | `GET /v1/wallets/{walletId}` | `wallets:read` | safe read | none | requests |
| `catalogue.list_categories()` / `list_categories_page()` | `GET /v1/wallets/{walletId}/catalog/categories` | `catalogue:read` | safe read | none | requests |
| `catalogue.list_subcategories()` / `list_subcategories_page()` | `GET /v1/wallets/{walletId}/catalog/categories/{categoryId}/subcategories` | `catalogue:read` | safe read | none | requests |
| `catalogue.get_subcategory()` | `GET /v1/wallets/{walletId}/catalog/subcategories/{subcategoryId}` | `catalogue:read` | safe read | none | requests |
| `catalogue.list_cards()` / `list_cards_page()` | `GET /v1/wallets/{walletId}/catalog/subcategories/{subcategoryId}/cards` | `catalogue:read` | safe read | none | requests |
| `orders.create()` / `resume()` | `POST /v1/wallets/{walletId}/orders` | `orders:create` | order | order JSON | requests, orders |
| `orders.get()` | `GET /v1/orders/{operationId}` | `orders:read`, or own-order permission | safe read | none | requests |
| `owned_cards.list()` / `list_page()` | `GET /v1/wallets/{walletId}/cards` | `cards:read` | safe read | none | requests |
| `owned_cards.get()` | `GET /v1/wallets/{walletId}/cards/{soldCardId}` | `cards:read` | safe read | none | requests |
| `owned_cards.reveal()` | `POST /v1/wallets/{walletId}/cards/{soldCardId}/reveal` | `cards:reveal` | nonce mutation | zero bytes | requests, reveals |
| `owned_cards.reveal_invoice()` | `POST /v1/wallets/{walletId}/invoices/{invoiceId}/cards/reveal` | `cards:reveal` | nonce mutation | zero bytes | requests, reveals |
| `diagnostics.check_signature()` | `POST /v1/diagnostics/signature` | `diagnostics:use` | nonce mutation | exactly `{}` | requests |
| `AnisEnrollmentClient.get()` | `GET /v1/enrollments/{invitationId}` | enrollment token | unsigned | none | — |
| `AnisEnrollmentClient.submit_key()` | `POST /v1/enrollments/{invitationId}/keys` | enrollment token | unsigned | public key | — |
| `AnisEnrollmentClient.submit_proof()` / `prove()` | `POST /v1/enrollments/{invitationId}/proof` | enrollment token | unsigned | proof | — |
| `AnisEnrollmentClient.get_status()` | `GET /v1/enrollments/{invitationId}/status` | enrollment token | unsigned | none | — |
| Key retrieval | `GET /.well-known/partner-signing-keys.json` | public | unsigned | none | — |

The `list()` methods follow every cursor page. Use the matching `list_*_page()` method when the application manages cursors itself. Pass each cursor back exactly as received.

The two reveal routes send no body, though the empty body digest is signed. The signature diagnostic sends `{}`. A proxy or middleware that adds a body or changes signed headers can cause refusal.

An address outside the network agreed with Anis and a missing permission may share the same `insufficient_scope` response. A missing or inaccessible resource may also share a response. This keeps the answer from revealing access policy.
