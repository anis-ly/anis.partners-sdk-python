"""The three request component lists accepted by the Partner gateway."""

from enum import StrEnum


class SignatureProfile(StrEnum):
    """Select Anis's closed route profiles so partners cannot accidentally sign a different component set."""

    #: Every GET covers request identity and date, without body digest or nonce.
    SAFE_READ = "SafeRead"

    #: Reveals and signature-check mutations include a digest and fresh nonce.
    BODYLESS_NONCE_MUTATION = "BodylessNonceMutation"

    #: Order creation also binds the caller's operation identity to prevent duplicate purchases.
    ORDER_MUTATION = "OrderMutation"

    @property
    def components(self) -> tuple[str, ...]:
        """Keep component names and ordering identical to Anis's verifier or the signature will fail."""
        if self is SignatureProfile.SAFE_READ:
            return ("@method", "@authority", "@path", "@query", "x-anis-date")
        if self is SignatureProfile.BODYLESS_NONCE_MUTATION:
            return ("@method", "@authority", "@path", "@query", "content-digest", "nonce", "x-anis-date")
        return (
            "@method",
            "@authority",
            "@path",
            "@query",
            "content-digest",
            "nonce",
            "idempotency-key",
            "x-anis-date",
        )
