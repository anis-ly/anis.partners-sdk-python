"""Accept only the response signature grammar Anis and this SDK agree to verify."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParsedSignatureInput:
    """Keep parsed fields explicit so ambiguous signature dictionaries cannot select a weaker interpretation."""

    label: str
    identifiers: tuple[str, ...]
    created: int
    key_id: str
    algorithm: str | None


def parse(value: str) -> ParsedSignatureInput | None:
    """Reject extra or loose grammar so an attacker cannot exploit parser disagreement about signed fields."""
    if not value:
        return None
    equals = value.find("=")
    if equals <= 0 or equals + 1 >= len(value) or value[equals + 1] != "(":
        return None
    label = value[:equals]
    index = equals + 2
    identifiers: list[str] = []
    while index < len(value) and value[index] != ")":
        if value[index] == " ":
            index += 1
            continue
        if value[index] != '"':
            return None
        end = value.find('"', index + 1)
        if end < 0:
            return None
        name = value[index + 1 : end]
        index = end + 1
        request_bound = False
        if index < len(value) and value[index] == ";":
            if not value.startswith(";req", index):
                return None
            request_bound = True
            index += 4
        identifiers.append(name + ";req" if request_bound else name)
    if index >= len(value) or value[index] != ")":
        return None
    index += 1
    created: int | None = None
    saw_created = False
    key_id: str | None = None
    algorithm: str | None = None
    while index < len(value):
        if value[index] != ";":
            return None
        index += 1
        name_end = value.find("=", index)
        if name_end < 0:
            return None
        name = value[index:name_end]
        index = name_end + 1
        if index < len(value) and value[index] == '"':
            end = value.find('"', index + 1)
            if end < 0:
                return None
            text = value[index + 1 : end]
            index = end + 1
            if name == "keyid":
                key_id = text
            elif name == "alg":
                algorithm = text
        else:
            end = index
            while end < len(value) and value[end] != ";":
                end += 1
            number_text = value[index:end]
            if not number_text.isascii() or not number_text.isdecimal():
                return None
            if name == "created":
                if saw_created:
                    return None
                try:
                    created = int(number_text)
                except ValueError:
                    return None
                if created > 9_223_372_036_854_775_807:
                    return None
                saw_created = True
            index = end
    if created is None or key_id is None:
        return None
    return ParsedSignatureInput(label, tuple(identifiers), created, key_id, algorithm)
