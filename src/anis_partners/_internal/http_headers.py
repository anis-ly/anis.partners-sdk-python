"""Interpret repeated HTTP field values without changing the joined signed representation."""


def has_true_value(value: str | None) -> bool:
    """Recognize any comma-separated true value when an HTTP field occurs more than once."""
    return any(item.strip().casefold() == "true" for item in value.split(",")) if value is not None else False
