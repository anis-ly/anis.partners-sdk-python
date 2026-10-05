"""Canonical UUID formatting for signed identifiers."""

from uuid import UUID


def canonical(value: str | UUID) -> str:
    """Return the lower-case hyphenated UUID form or raise ValueError."""
    try:
        return str(value if isinstance(value, UUID) else UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("A canonical UUID is required.") from exc
