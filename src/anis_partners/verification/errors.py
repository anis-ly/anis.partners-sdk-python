"""Exception raised when a response is unsafe to return to the caller."""

from anis_partners.errors.base import AnisPartnersError
from anis_partners.verification.failures import ResponseVerificationFailure


class UnverifiableResponseError(AnisPartnersError):
    """Prevent callers from treating an unverified response as usable and expose only a safe refusal reason."""

    def __init__(self, failure: ResponseVerificationFailure) -> None:
        """Keep body and key data out of exception text while telling the caller why trust was refused."""
        self.failure = failure
        super().__init__(f"The Anis response could not be verified ({failure.value}); its content was discarded.")

    def __reduce__(self) -> tuple[type["UnverifiableResponseError"], tuple[ResponseVerificationFailure]]:
        """Keep the bounded verification reason intact across exception copying and serialization."""
        return (type(self), (self.failure,))
