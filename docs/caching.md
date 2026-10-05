# Signing key cache

The public response-verification keys are fetched separately from signed API responses. Each client keeps them in process memory for the configured cache duration (600 seconds by default). In a multi-worker application, each worker otherwise fetches the same key document independently and can temporarily observe a rotation at a different time.

The shared cache is part of the trust boundary: its signing-key namespace must be writable only by your application and trusted operators. Anyone who can replace a cached document can supply a different public key and make matching responses appear authentic. Do not share this cache namespace with tenants or untrusted workloads.

Pass a shared object that implements the public `KeyDocumentCache` protocol to the client as `key_cache`. Its `get(key)` method returns the cached JSON string or `None`; `set(key, value, ttl_seconds)` stores that string for the bounded lifetime. The SDK uses a cache key derived from the lower-cased authority. The cache contains public signing keys only. After a response refers to an unknown key id, the SDK refreshes from the authority once rather than trusting a stale document indefinitely.

For example, adapt Django's cache framework:

```python
from django.core.cache import cache as django_cache


class DjangoSigningKeyCache:
    """Bridge Django's shared cache to the SDK's small cache interface."""

    def get(self, key: str) -> str | None:
        value = django_cache.get(key)
        return value if isinstance(value, str) else None

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        django_cache.set(key, value, timeout=ttl_seconds)


with AnisPartnersClient(options, signer, key_cache=DjangoSigningKeyCache()) as anis:
    profile = anis.profile.get()
```

Use a shared cache service for separate processes, such as Django's configured Memcached backend. A per-process dictionary can reduce repeat reads inside one worker, but it is not shared between workers. Do not use this hook for credentials or private keys.
