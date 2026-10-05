"""Canonical facts shared by the request base and emitted headers."""

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from uuid import UUID

from anis_partners._internal.uuid import canonical


@dataclass(frozen=True, slots=True)
class SignatureInputs:
    """Freeze canonical request facts once because the base and emitted headers must describe one request."""

    #: Method is upper-cased once because the gateway signs the same canonical verb.
    method: str
    #: Host and non-default port are lower-cased before either base or header uses them.
    authority: str
    #: Absolute route path; escaped paths are refused because the gateway signs the decoded path.
    path: str
    #: Raw query without '?' so parameter order and escaping survive unchanged.
    canonical_query: str
    #: UTC request date shared by the signature base and emitted header.
    anis_date: str
    #: Digest of the exact body bytes that will be sent.
    content_digest: str | None = None
    #: Fresh nonce on mutation profiles; absent on reads.
    nonce: str | None = dataclass_field(default=None, repr=False)
    #: Caller-owned UUID used only for order creation and safe retry.
    idempotency_key: str | UUID | None = None
    #: Scheme selects the correct default port to omit from the authority.
    scheme: str = "https"

    def __post_init__(self) -> None:
        """Reject escaped paths and canonicalize shared values once so signing and transport cannot disagree."""
        if "%" in self.path:
            raise ValueError("A request path containing percent escapes cannot be signed.")
        object.__setattr__(self, "method", self.method.upper())
        authority = self.authority.lower()
        default_port = {"http": ":80", "https": ":443"}.get(self.scheme.lower())
        if default_port is not None and authority.endswith(default_port):
            authority = authority[: -len(default_port)]
        object.__setattr__(self, "authority", authority)
        if self.idempotency_key is not None:
            object.__setattr__(self, "idempotency_key", canonical(self.idempotency_key))

    @property
    def query_component_value(self) -> str:
        """Preserve the required `?` even for an empty query, matching Anis's canonical request base."""
        return "?" + self.canonical_query

    def value_of(self, component: str) -> str:
        """Use stored values for every component so headers and signature input cannot recanonicalize differently."""
        values = {
            "@method": self.method,
            "@authority": self.authority,
            "@path": self.path,
            "@query": self.query_component_value,
            "content-digest": self.content_digest,
            "nonce": self.nonce,
            "idempotency-key": str(self.idempotency_key) if self.idempotency_key is not None else None,
            "x-anis-date": self.anis_date,
        }
        value = values.get(component)
        if value is None:
            raise ValueError(f"The covered request component {component!r} has no value.")
        return value
