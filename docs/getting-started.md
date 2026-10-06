# Getting started

> **Disclaimer.** This SDK is an optional helper provided free of charge under the MIT License, "as is", without
> warranty of any kind. Anis (Aniscom for Technical Services) accepts no responsibility or liability for its use or for
> any loss arising from it. You remain responsible for your own integration — recording orders before you send them,
> recovery, key custody and testing. The source code is public: read it to understand exactly what it does before you
> rely on it. You do not need an SDK — you can integrate directly with the Anis Partner API using the documentation at
> https://developers.anis.ly.

## 1. Enroll a signing key

Anis staff provide an invitation id and a single-use enrollment token for your application. Generate a P-256 key pair and save the private key under your control before submitting its public half. The private key never needs to leave your system.

```python
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from anis_partners import AnisEnrollmentClient, EnrollmentKeyRequest, PemP256Signer

authority = "https://<authority Anis gave you>"
invitation_id = UUID("<invitation id>")
enrollment_token = "<single-use token>"
key_path = Path("/secure/anis/partner-key.pem")

private_key = ec.generate_private_key(ec.SECP256R1())
pem = private_key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)
key_path.parent.mkdir(parents=True, exist_ok=True)
descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "wb") as key_file:
    key_file.write(pem)
    key_file.flush()
    os.fsync(key_file.fileno())
signer = PemP256Signer.from_pem(pem)
now = datetime.now(UTC)

with AnisEnrollmentClient(authority, invitation_id, enrollment_token) as enrollment:
    print(enrollment.get())
    submitted = enrollment.submit_key(
        EnrollmentKeyRequest(signer.public_jwk(), now, now + timedelta(days=365))
    )
    proof_status = enrollment.prove(submitted, signer)
    if proof_status.proof_state != "accepted":
        raise RuntimeError("The proof was not accepted; ask Anis staff to restart this enrollment.")
    print(f"Key id: {submitted.key_id}")
    print(f"Safety code: {submitted.safety_code}; read this to Anis staff when they call.")
```

Anis staff call your technical contact and ask for the 16-character safety code. They compare it with the key they received and confirm the key. The key can sign requests when `get_status()` reports `active`; a proof being accepted alone does not activate it. Keep the safety code available to the person who answers the call. Do not send a key fingerprint to anyone.

The enrollment client checks that the verified key thumbprint matches the public key you submitted. If they differ, it raises `EnrollmentKeyMismatchError` and refuses to build a proof. A proof state other than `accepted` is an answer, not an API refusal; do not treat it as activation.

## 2. Configure the client

```python
from anis_partners import AcceptLanguage, ClientOptions

options = ClientOptions(
    authority="https://<authority Anis gave you>",
    signature_lifetime_seconds=60,  # 1–60 seconds
    accept_language=AcceptLanguage.ARABIC,  # presentation only
    signing_key_cache_seconds=600,
    timeout_seconds=30,
)
```

Settings may also come from a mapping. Python code should use the snake_case names:

```python
from anis_partners import ClientOptions

options = ClientOptions.from_mapping(
    {
        "authority": "https://<authority Anis gave you>",
        "signature_lifetime_seconds": 60,
        "accept_language": "Arabic",
        "signing_key_cache_seconds": 600,
        "timeout_seconds": 30,
    }
)
```

For a settings file shared across runtimes, `from_mapping` also accepts an `AnisPartners` section with the camelCase keys `authority`, `signatureLifetime`, `acceptLanguage`, `signingKeyCacheDuration`, and `timeout`. PascalCase names remain accepted for compatibility; Python examples should use snake_case.

There is no default signer because the right place for a private key depends on your environment. `PemP256Signer.from_pem_file(path).for_key(key_id)` loads a local P-256 PEM key. A vault or hardware signer can implement the same `sign(data: bytes) -> bytes` seam and return a 64-byte P1363 signature.

## 3. Make your first call

```python
from anis_partners import AnisPartnersClient, PemP256Signer

signer = PemP256Signer.from_pem_file("/secure/anis/partner-key.pem").for_key("<active key id>")
with AnisPartnersClient(options, signer) as anis:
    profile = anis.profile.get()
    for wallet in anis.wallets.list():  # follows every cursor page
        print(wallet.name, wallet.balance)
```

Use `AsyncAnisPartnersClient` when the application is already async:

```python
import asyncio

from anis_partners import AsyncAnisPartnersClient, ClientOptions, PemP256Signer


async def main() -> None:
    options = ClientOptions("https://<authority Anis gave you>")
    signer = PemP256Signer.from_pem_file("/secure/anis/partner-key.pem").for_key("<active key id>")
    async with AsyncAnisPartnersClient(options, signer) as anis:
        profile = await anis.profile.get()
        async for wallet in anis.wallets.list():
            print(profile.application.id if profile.application else "No application", wallet.name, wallet.balance)


if __name__ == "__main__":
    asyncio.run(main())
```

Both clients use the same request, order, and response-verification rules. An injected `httpx.Client` or `httpx.AsyncClient` remains owned by the host; the context manager closes only a client the SDK created.

## 4. When a signature will not verify

Every response is verified before a model is returned. For reads, `UnverifiableResponseError.failure` identifies the failed rule and the answer body is discarded. For an order, the result is `OrderOutcomeUnknown`: the order may have completed, so resume with the same operation id and exact request. The SDK refreshes its signing-key document once when the response names an unknown key.

Use `anis.diagnostics.check_signature()` (or `await anis.diagnostics.check_signature()`) when a signature is refused. The diagnostic result reports the request facts Anis used to rebuild the signature base. Check the active key id, host clock, and whether an intermediary rewrites the request. A response verification error is separate from an API refusal: it means the SDK could not prove the answer came from Anis.

## Calling Anis from an Odoo module

Keep the PEM private key in a protected secret mount or a file under the Odoo service account's private data directory, for example `<odoo data directory>/anis/partner-key.pem`. Create the file with owner-only read and write permissions (`0o600`), keep it out of the add-on source tree and database, and configure its path and key id through the deployment environment. Do not store the PEM contents in an Odoo system parameter.

Create one `AnisPartnersClient` per worker process and reuse it for that worker's requests. Do not create a new connection pool for each model method call. Close the client during worker shutdown. If the SDK owns its HTTP client, use the context manager in the worker lifecycle; if Odoo provides an `httpx.Client`, inject it and close it according to the worker's resource lifecycle.

Odoo workers have separate memory. Supply a shared `KeyDocumentCache` backed by Odoo's configured cache integration or a shared Redis/Memcached adapter so each worker can reuse the published signing-key document. The cache is only for public verification keys and has a bounded time-to-live; see [Signing key cache](caching.md). Do not use Django cache APIs in an Odoo module.

Use Odoo's ORM for the durable order journal and Odoo cron or a queue job for delayed recovery. In one database transaction, create and commit the intent with a fresh operation UUID, wallet, and exact request before making the Anis call. Record the verified outcome in a later transaction. A process restart can then resume the same saved intent rather than creating a second purchase.

Revealed card codes are secrets. Pass them directly to the protected fulfillment path, never put them in application logs, exception messages, chatter, or audit notes. Log an order id and its outcome instead.
