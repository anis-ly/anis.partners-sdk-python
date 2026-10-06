# Security and key custody

## Keep the signing key under your control

The SDK has no default key path, does not read private-key material from an environment variable, and does not persist private keys. `PemP256Signer.from_pem_file(path)` is provided for a protected PEM file. A managed signer may implement `RequestSigner`: a `key_id` property and `sign(data: bytes) -> bytes` returning the 64-byte signature format required by the API. This seam lets a KMS or HSM perform signing without exporting its private key.

```python
class HardwareSigner:
    """Adapt a protected signing service to the SDK's signer protocol."""

    key_id = "<active key id>"

    def sign(self, data: bytes) -> bytes:
        # Sign data with P-256/SHA-256, then convert the result to fixed-width P1363 r || s.
        return hardware_service.sign_p256_sha256(self.key_id, data)
```

ECDSA libraries commonly return ASN.1 DER signatures, which have variable length. The Partner API requires IEEE P1363: 32-byte big-endian `r` followed by 32-byte big-endian `s`, exactly 64 bytes. A signer adapter must convert DER before returning; a DER signature is not interchangeable even though it represents the same mathematical signature.

## Requests and responses

Each signed request covers its method, authority, path, query, date, and profile-specific fields. Mutation bodies are bound using `Content-Digest`; a nonce prevents replay, and an order carries the caller's idempotency key. Every response is verified against Anis's published signing keys before its body is parsed. There is no option to disable verification. If verification fails, the body is discarded; an order answer that cannot be verified has an unknown outcome.

The default signature lifetime is 60 seconds and the supported setting is 1–60 seconds. Use an accurate UTC system clock. The server's request admission window is wider, but accepting an old response can lose credentials after a sale; the SDK keeps its response freshness window bounded. Plain HTTP is permitted only for loopback testing; use HTTPS for every network authority.

## Enrollment

Protect the private half before submitting a public key. After proof, an Anis staff member checks the derived safety code by phone and activates the key. Enrollment tokens are secrets; do not log them or include them in support requests. Read status and confirm `active` before using the key for partner calls.

## Rotation

Anis staff start a rotation, then you enroll a replacement key and complete the safety-code check. During the overlap, requests may be signed by either the old or replacement key; keep both private keys available until Anis confirms completion and every worker has moved to the replacement. A revoked key is refused as `invalid_credentials`. The SDK fetches the public key document and refreshes it once when a response uses an unknown key id. Its default in-process cache is ten minutes; a host can supply a shared `KeyDocumentCache` with a bounded TTL. Rotation is managed by key state at Anis, not by a local environment switch.

## Card credentials

Revealed codes are returned only by explicit reveal calls or the first verified completed-order response. Keep them in a protected credential store, mask them in user interfaces, and never write them to logs, traces, metrics, support tickets, or exception text. A replayed order contains no codes. Use the invoice reveal route only when access permits and the codes are needed again.
