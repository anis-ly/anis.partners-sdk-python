"""Clock seam for deterministic signature verification."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Provides an aware UTC time for signature freshness checks."""

    def now(self) -> datetime:
        """Return the current aware UTC time."""


@dataclass(frozen=True, slots=True)
class SystemClock:
    """Reads the current system time in UTC."""

    def now(self) -> datetime:
        """Return the current aware UTC time."""
        return datetime.now(UTC)
