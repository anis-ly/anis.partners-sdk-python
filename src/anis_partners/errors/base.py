"""Common public base for failures raised deliberately by the SDK."""

from __future__ import annotations


class AnisPartnersError(Exception):
    """Catch SDK-owned failures without swallowing unrelated application input errors."""


class KeyDocumentUnavailableError(AnisPartnersError):
    """Report an unusable signing-key document without exposing its body or private key material."""

    def __init__(self, message: str, error_type: str = "connection") -> None:
        """Retain the bounded transport reason so callers can distinguish timeout from connection failure."""
        super().__init__(message)
        self.error_type = error_type

    def __reduce__(self) -> tuple[type[KeyDocumentUnavailableError], tuple[str, str]]:
        """Preserve the transport classification when hosts copy or serialize this SDK error."""
        return type(self), (str(self), self.error_type)
