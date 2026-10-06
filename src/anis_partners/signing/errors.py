"""Partner-facing request-signing failure."""

from anis_partners.errors.base import AnisPartnersError


class RequestSigningError(AnisPartnersError):
    """Tell the caller signing failed before the request was sent, preserving the vault or HSM cause."""
