"""Exception raised when a notification is unsafe to act on."""

from anis_partners.errors.base import AnisPartnersError
from anis_partners.verification.webhook_failures import WebhookVerificationFailure


class UnverifiableWebhookError(AnisPartnersError):
    """Prevent receivers from acting on an unverified notification and expose only a safe refusal reason."""

    def __init__(self, failure: WebhookVerificationFailure) -> None:
        """Keep body and key data out of exception text while telling the receiver why trust was refused."""
        self.failure = failure
        super().__init__(f"The Anis notification could not be verified ({failure.value}); its content was discarded.")

    def __reduce__(self) -> tuple[type["UnverifiableWebhookError"], tuple[WebhookVerificationFailure]]:
        """Keep the bounded verification reason intact across exception copying and serialization."""
        return (type(self), (self.failure,))
