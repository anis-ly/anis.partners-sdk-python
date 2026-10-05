"""Small JSON conversion helpers shared by the immutable wire models."""

import json
import re
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal, TypeVar, cast, overload
from uuid import UUID

JsonObject = Mapping[str, object]
E = TypeVar("E", bound=StrEnum)


def object_data(data: object) -> JsonObject:
    """Read a JSON object while rejecting scalar or array model inputs."""
    value = json.loads(data) if isinstance(data, (str, bytes, bytearray)) else data
    if not isinstance(value, Mapping):
        raise ValueError("A model must be read from a JSON object.")
    return cast(JsonObject, value)


def field(data: JsonObject, name: str) -> object:
    """Return a wire member or None so omitted optional fields remain absent values."""
    return data.get(name)


def text(value: object, default: str | None = None) -> str | None:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError("A text model member must be a string or null.")
    return value


def integer(value: object, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("An integer model member must be an integer.")
    return value


def boolean(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError("A boolean model member must be true or false.")
    return value


@overload
def identifier(value: object, *, optional: Literal[True]) -> UUID | None: ...


@overload
def identifier(value: object, *, optional: Literal[False] = False) -> UUID: ...


def identifier(value: object, *, optional: bool = False) -> UUID | None:
    if value is None:
        return None if optional else UUID(int=0)
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValueError("An identifier model member must be a UUID string.")
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValueError("An identifier model member must be a UUID string.") from exc


def timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("A timestamp must be an ISO 8601 datetime.") from exc
    else:
        raise ValueError("A timestamp must be an ISO 8601 string or null.")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("A timestamp must include a timezone.")
    return parsed.astimezone(UTC)


def calendar_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        raise ValueError("A calendar date must not include a time.")
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError("A calendar date must be an ISO 8601 date string or null.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("A calendar date must be an ISO 8601 date string.") from exc


def lenient_enum(enum_type: type[E], value: object, unknown: E) -> E:
    """Map future or malformed enum values to the model's explicit Unknown member."""
    if not isinstance(value, str):
        return unknown
    normalized = value.casefold()
    for member in enum_type:
        camel_name = re.sub(r"_([a-z])", lambda match: match.group(1).upper(), member.name.lower())
        if normalized in {member.value.casefold(), member.name.casefold(), camel_name.casefold()}:
            return member
    return unknown


def model_json(instance: object) -> dict[str, object]:
    """Serialize dataclass fields with .NET-compatible camelCase names and nested wire forms."""
    if not is_dataclass(instance):
        raise TypeError("Only dataclass models can be serialized.")
    output: dict[str, object] = {}
    for item in fields(instance):
        value = getattr(instance, item.name)
        if value is None:
            continue
        output[camel_case(item.name)] = wire_value(value)
    return output


def camel_case(name: str) -> str:
    return re.sub(r"_([a-z])", lambda match: match.group(1).upper(), name)


def wire_timestamp(value: datetime, *, seconds_only: bool = False) -> str:
    utc_value = timestamp(value)
    if utc_value is None:
        raise ValueError("A timestamp must not be null.")
    timespec = "seconds" if seconds_only else "auto"
    return utc_value.isoformat(timespec=timespec).replace("+00:00", "Z")


def wire_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return wire_timestamp(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (list, tuple)):
        return [wire_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): wire_value(item) for key, item in value.items()}
    to_json = getattr(value, "to_json", None)
    if callable(to_json):
        return to_json()
    if is_dataclass(value):
        return model_json(value)
    raise TypeError(f"Unsupported model value type: {type(value).__name__}.")
