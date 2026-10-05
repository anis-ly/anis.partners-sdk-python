"""Rebuild response bytes independently so advertised components cannot omit data the client received."""

from dataclasses import dataclass
from typing import Final

MAX_AGE_SECONDS: Final = 60
ALGORITHM: Final = "ecdsa-p256-sha256"


@dataclass(frozen=True, slots=True)
class ResponseComponent:
    """Represent a signed response field so its value and request binding stay inseparable."""

    name: str
    value: str
    request_bound: bool = False

    @property
    def identifier(self) -> str:
        """Preserve RFC quoting and `;req` so request-bound responses cannot be detached from this request."""
        return f'"{self.name}"' + (";req" if self.request_bound else "")


def components(
    status: int,
    content_digest: str,
    request_id: str,
    request_signature_input: str | None,
    location: str | None,
    retry_after: str | None,
    idempotency_replayed: str | None,
    cache_control: str | None,
) -> tuple[ResponseComponent, ...]:
    """Rebuild the contract's ordered profile so a server cannot choose which received fields are authenticated."""
    result = [
        ResponseComponent("@status", str(status)),
        ResponseComponent("content-digest", content_digest),
        ResponseComponent("x-request-id", request_id),
    ]
    if request_signature_input:
        result.append(ResponseComponent("signature-input", request_signature_input, True))
    for name, value in (
        ("location", location),
        ("retry-after", retry_after),
        ("idempotency-replayed", idempotency_replayed),
        ("cache-control", cache_control),
    ):
        if value:
            result.append(ResponseComponent(name, value))
    return tuple(result)


def parameters(parts: tuple[ResponseComponent, ...], created: int, key_id: str) -> str:
    """Bind creation time and key identity; response freshness is enforced locally because no expiry is signed."""
    return f'({" ".join(part.identifier for part in parts)});created={created};keyid="{key_id}";alg="{ALGORITHM}"'


def build(parts: tuple[ResponseComponent, ...], created: int, key_id: str) -> bytes:
    """Match exact RFC bytes; an extra newline would make a valid response appear forged."""
    lines = [f"{part.identifier}: {part.value}" for part in parts]
    lines.append(f'"@signature-params": {parameters(parts, created, key_id)}')
    return "\n".join(lines).encode("utf-8")
