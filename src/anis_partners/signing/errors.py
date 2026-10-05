"""Partner-facing request-signing failure."""


class RequestSigningError(RuntimeError):
    """Tell the caller signing failed before the request was sent, preserving the vault or HSM cause."""
