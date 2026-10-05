# Anis Partners for Python

The Python client for the Anis Partner API. It signs every request, verifies every response, and gives each operation a typed result. The details that can cause duplicate purchases or expose unverified credentials are handled explicitly: caller-owned order ids, recovery outcomes, and response verification have no silent shortcuts.

```bash
pip install anis-partners
# or
uv add anis-partners
```

- [Getting started](https://github.com/anis.partners-sdk-python/blob/main/docs/getting-started.md) — enrollment, configuration, first call, sync and async use
- [Orders and recovery](https://github.com/anis.partners-sdk-python/blob/main/docs/orders-and-recovery.md) — read before placing an order
- [Routes and permissions](https://github.com/anis.partners-sdk-python/blob/main/docs/routes-and-permissions.md) — routes, permissions, bodies, and limits
- [Errors](https://github.com/anis.partners-sdk-python/blob/main/docs/errors.md) — stable error codes and typed exceptions
- [Security and key custody](https://github.com/anis.partners-sdk-python/blob/main/docs/security.md)
- [Observability](https://github.com/anis.partners-sdk-python/blob/main/docs/observability.md)
- [Signing key cache](https://github.com/anis.partners-sdk-python/blob/main/docs/caching.md) — shared cache for multi-process applications
- [Runnable sample](https://github.com/anis.partners-sdk-python/blob/main/samples/console/README.md)

## Quick start

```python
from anis_partners import AnisPartnersClient, ClientOptions, PemP256Signer

options = ClientOptions("https://<authority Anis gave you>")
signer = PemP256Signer.from_pem_file("/secure/partner-key.pem").for_key("<active key id>")

with AnisPartnersClient(options, signer) as anis:
    profile = anis.profile.get()
    wallets = list(anis.wallets.list())  # follows every cursor page
    print(profile.application.id if profile.application else "No application")
    print(f"Found {len(wallets)} wallets")
```

The async client returns the same results. Run the whole flow inside an event loop:

```python
import asyncio

from anis_partners import AsyncAnisPartnersClient, ClientOptions, PemP256Signer


async def main() -> None:
    options = ClientOptions("https://<authority Anis gave you>")
    signer = PemP256Signer.from_pem_file("/secure/partner-key.pem").for_key("<active key id>")
    async with AsyncAnisPartnersClient(options, signer) as anis:
        profile = await anis.profile.get()
        wallets = [wallet async for wallet in anis.wallets.list()]
        print(profile.application.id if profile.application else "No application")
        print(f"Found {len(wallets)} wallets")


if __name__ == "__main__":
    asyncio.run(main())
```

For order creation and recovery, persist the operation id and exact request before calling the SDK. See [Orders and recovery](https://github.com/anis.partners-sdk-python/blob/main/docs/orders-and-recovery.md) for the complete outcome rules.

## Refusals built into the design

The caller supplies the order id. A dropped answer followed by a new id could buy twice, so the SDK never invents this identity. The five order result types distinguish a completed sale, processing, a replay, a definitive refusal, and an unknown outcome. Only the first completion returns credentials; a replay never repeats them.

An unknown result means the original sale may have completed. Resume with the same id and body. A new purchase uses a new id only after a definitive `OrderNotPlaced` result and a changed intent.

Response verification cannot be disabled. If a read response cannot be verified, its body is discarded and `UnverifiableResponseError` is raised. An unverifiable order answer is `OrderOutcomeUnknown`, because the sale may already have completed.

## What is covered

The SDK covers all 19 published routes across `profile`, `wallets`, `catalogue`, `orders`, `owned_cards`, and `diagnostics`, plus the enrollment client. Public errors are generated from the error catalogue. Request, response, safety-code, and enrollment vectors are tested along with signed in-memory client flows and contract drift checks.

This package is at parity with the .NET SDK `Anis.Partners` 1.3.0. Supported Python versions are 3.11–3.14.

### Proven live

Proven live: not yet. A live run is planned separately; vector and in-memory tests do not claim live-service certification.

## Regenerating error types

`src/anis_partners/errors/_codes.py` is generated from `contracts/error-catalogue.json`. Regenerate it with:

```bash
uv run python tools/generate_errors.py
```

Do not edit the generated file by hand; the contract drift test checks it.

## License

[MIT](https://github.com/anis.partners-sdk-python/blob/main/LICENSE) © 2026 Aniscom for Technical Services (Anis).
