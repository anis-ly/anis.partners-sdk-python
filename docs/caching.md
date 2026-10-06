# Signing key cache

The public response-verification keys are fetched separately from signed API responses. Each client keeps them in process memory for the configured cache duration (600 seconds by default). In a multi-worker application, each worker otherwise fetches the same key document independently and can temporarily observe a rotation at a different time.

The shared cache is part of the trust boundary: its signing-key namespace must be writable only by your application and trusted operators. Anyone who can replace a cached document can supply a different public key and make matching responses appear authentic. Do not share this cache namespace with tenants or untrusted workloads.

Pass a shared object that implements the public `KeyDocumentCache` protocol to the client as `key_cache`. Its `get(key)` method returns the cached JSON string or `None`; `set(key, value, ttl_seconds)` stores that string for the bounded lifetime. The SDK uses a cache key derived from the lower-cased authority. The cache contains public signing keys only. After a response refers to an unknown key id, the SDK refreshes from the authority once rather than trusting a stale document indefinitely.

For example, adapt the shared cache service already used by your host application:

```python
from typing import Protocol


from anis_partners import AnisPartnersClient, ClientOptions, PemP256Signer


class CacheBackend(Protocol):
    def get(self, key: str) -> object: ...

    def set(self, key: str, value: str, ttl_seconds: int) -> None: ...


class HostSigningKeyCache:
    """Adapt the host's shared cache without making public key reads depend on it."""

    def __init__(self, backend: CacheBackend) -> None:
        self._backend = backend

    def get(self, key: str) -> str | None:
        value = self._backend.get(key)
        return value if isinstance(value, str) else None

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._backend.set(key, value, ttl_seconds)


def read_profile(backend: CacheBackend, key_path: str, authority: str, key_id: str) -> None:
    options = ClientOptions(authority)
    signer = PemP256Signer.from_pem_file(key_path).for_key(key_id)
    with AnisPartnersClient(options, signer, key_cache=HostSigningKeyCache(backend)) as anis:
        profile = anis.profile.get()
        print(profile.application.id if profile.application else "No application")
```

Use a shared cache service across worker processes. In Odoo, use Odoo's configured cache integration or a shared Redis/Memcached adapter; Odoo's ORM and cron own persistence and scheduled work. A per-process dictionary is not shared between workers. Do not use this hook for credentials or private keys.
