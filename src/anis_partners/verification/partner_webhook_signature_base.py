"""Rebuild the notification signature base independently so the sender cannot choose what is authenticated."""

from typing import Final

ALGORITHM: Final = "ecdsa-p256-sha256"
TAG: Final = "anis-partner-webhook-v1"
LABEL: Final = "sig1"
LIFETIME_SECONDS: Final = 300
MAX_SKEW_SECONDS: Final = 300
COMPONENTS: Final = (
    "@method",
    "@target-uri",
    "content-digest",
    "webhook-id",
    "anis-webhook-attempt",
    "anis-application-id",
)


def parameters(created: int, expires: int, key_id: str) -> str:
    """Render the covered list and parameters; they are signed last and bind lifetime and key identity."""
    covered = " ".join(f'"{name}"' for name in COMPONENTS)
    return f'({covered});created={created};expires={expires};keyid="{key_id}";alg="{ALGORITHM}";tag="{TAG}"'


def build(
    configured_url: str,
    content_digest: str,
    webhook_id: str,
    attempt: str,
    application_id: str,
    created: int,
    expires: int,
    key_id: str,
) -> bytes:
    """Match the exact RFC 9421 bytes: LF separators, no trailing newline, signature parameters last."""
    lines = [
        '"@method": POST',
        f'"@target-uri": {configured_url}',
        f'"content-digest": {content_digest}',
        f'"webhook-id": {webhook_id}',
        f'"anis-webhook-attempt": {attempt}',
        f'"anis-application-id": {application_id}',
        f'"@signature-params": {parameters(created, expires, key_id)}',
    ]
    return "\n".join(lines).encode("utf-8")
