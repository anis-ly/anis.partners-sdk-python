"""Preserve buffered bytes and sent-request context so verification covers the actual exchange."""

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class VerifiableResponse:
    """Capture the exact exchange because re-reading or omitting request context breaks signature binding."""

    #: HTTP status is covered so a signed body cannot be moved to another outcome.
    status: int
    #: Received headers used to rebuild the profile instead of trusting server-advertised coverage.
    headers: Mapping[str, str] = field(repr=False)
    #: Exact buffered bytes whose digest must match before the caller can consume the body.
    body: bytes = field(repr=False)
    #: Original client value needed to verify `;req` binding and prevent response substitution.
    request_signature_input: str | None = field(default=None, repr=False)
