"""Accept only the notification signature grammar Anis and this SDK agree to verify."""

import re
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class ParsedWebhookSignatureInput:
    """Keep parsed fields explicit so ambiguous signature dictionaries cannot select a weaker interpretation."""

    label: str
    #: The covered list exactly as received, so reduced or reordered coverage is refused even when signed.
    covered: str
    created: int
    #: Kept as received because a missing or non-numeric value is a lifetime failure, not a syntax failure.
    expires: str | None
    key_id: str
    algorithm: str
    tag: str | None


_LABEL_PATTERN: Final = r"[a-z][a-z0-9_*.-]*"
_INPUT: Final = re.compile(
    r"(" + _LABEL_PATTERN + r')=(\((?:"[^"\r\n]*"(?: "[^"\r\n]*")*)?\)(?:;[a-z][a-zA-Z0-9]*=(?:"[^"\r\n]*"|[0-9]+))*)'
)
_PARAMETER: Final = re.compile(r';([a-z][a-zA-Z0-9]*)=("[^"]*"|[0-9]+)')
_ORDER: Final = ("created", "expires", "keyid", "alg", "tag")
_MAX_INSTANT: Final = 9_223_372_036_854_775_807


def parse(value: str) -> ParsedWebhookSignatureInput | None:
    """Reject extra, repeated, reordered or loose grammar so parser disagreement cannot change the signed fields."""
    match = _INPUT.fullmatch(value)
    if match is None:
        return None
    label, parameters = match.groups()
    end = parameters.index(")") + 1
    covered = parameters[:end]
    pairs = _PARAMETER.findall(parameters[end:])
    names = [name for name, _ in pairs]
    fields = dict(pairs)
    if (
        len(names) != len(fields)
        or any(name not in _ORDER for name in names)
        or names != [name for name in _ORDER if name in fields]
        or any(name not in fields for name in ("created", "keyid", "alg"))
        or not re.fullmatch(r"[0-9]+", fields["created"])
        or len(fields["created"]) > len(str(_MAX_INSTANT))
        or int(fields["created"]) > _MAX_INSTANT
        or any(not fields[name].startswith('"') for name in ("keyid", "alg"))
        or fields["keyid"] == '""'
        or ("tag" in fields and not fields["tag"].startswith('"'))
    ):
        return None
    tag = fields["tag"][1:-1] if "tag" in fields else None
    return ParsedWebhookSignatureInput(
        label,
        covered,
        int(fields["created"]),
        fields.get("expires"),
        fields["keyid"][1:-1],
        fields["alg"][1:-1],
        tag,
    )
