"""Immutable headers produced together from a request's covered components."""

from dataclasses import dataclass
from dataclasses import field as dataclass_field


@dataclass(frozen=True, slots=True)
class SignedRequestHeaders:
    """Keep all signature headers together so callers cannot send a mismatched partial signing result."""

    #: Advertises the covered bytes; changing this list makes verification fail.
    signature_input: str = dataclass_field(repr=False)
    #: Carries the P1363 signature Anis verifies against the advertised components.
    signature: str = dataclass_field(repr=False)
    #: The request's canonical UTC date.
    anis_date: str
    #: Digest header for requests whose profile carries a body.
    content_digest: str | None
    #: Mutation replay protection value, absent on safe reads.
    nonce: str | None = dataclass_field(repr=False)
    #: Caller-supplied order identity, absent on other routes.
    idempotency_key: str | None
    #: Exact signed bytes for diagnostics; protect them because they can aid offline signature guessing.
    signature_base: bytes = dataclass_field(repr=False)

    def __repr__(self) -> str:
        """Show signing metadata without printing values that can replay or disclose the signed request."""
        return (
            "SignedRequestHeaders(signature_input=<redacted>, signature=<redacted>, "
            f"anis_date={self.anis_date!r}, content_digest={self.content_digest!r}, nonce=<redacted>, "
            f"idempotency_key={self.idempotency_key!r}, signature_base=<redacted>)"
        )
