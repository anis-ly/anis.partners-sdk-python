"""Canonical UUID formatting for signed identifiers."""

from uuid import UUID


def parse(value: str | UUID, argument_name: str) -> UUID:
    """Parse a caller-supplied identifier while keeping argument mistakes out of signing errors."""
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{argument_name} must be a UUID or string.")
    try:
        return UUID(value)
    except ValueError:
        raise ValueError(f"{argument_name} must be a valid UUID.") from None


def canonical(value: str | UUID) -> str:
    """Return the lower-case hyphenated UUID form or raise ValueError."""
    try:
        return str(value if isinstance(value, UUID) else UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("A canonical UUID is required.") from exc
