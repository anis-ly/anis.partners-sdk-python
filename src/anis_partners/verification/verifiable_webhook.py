"""Preserve the received request so verification covers the exact bytes Anis signed."""

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class VerifiableWebhook:
    """Capture the delivery as received because re-serialized or re-routed content breaks signature binding."""

    #: Actual HTTP method; anything other than POST is refused.
    method: str
    #: Actual absolute URL the receiver served, compared with the configured URL byte for byte.
    target_uri: str
    #: Received headers; names are matched case-insensitively and duplicates are refused.
    headers: Mapping[str, str] = field(repr=False)
    #: Exact raw bytes read before any JSON middleware touched them.
    body: bytes = field(repr=False)
