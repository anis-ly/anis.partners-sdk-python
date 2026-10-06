"""Exact decimal money values for prices read from and sent to Anis."""

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext

from anis_partners.models._json import field, object_data, text, timestamp, wire_timestamp

_SCALE = Decimal("0.001")
_DECIMAL_PRECISION = 29
_AMOUNT_TEXT = re.compile(r"-?[0-9]+(?:\.[0-9]+)?\Z")
_AMOUNT_ERROR = "Anis amounts have at most three decimal places"


@dataclass(frozen=True, slots=True)
class Money:
    """Keep price arithmetic decimal-only so expected totals cannot drift through binary floats."""

    amount: Decimal
    currency: str
    as_of: datetime | None = None

    def __post_init__(self) -> None:
        if isinstance(self.amount, float):
            raise TypeError("Money amounts cannot be constructed from float values.")
        if not isinstance(self.amount, Decimal):
            raise TypeError("Money amounts must be Decimal values.")
        if not isinstance(self.currency, str):
            raise TypeError("Money currency must be a string.")
        if not self.amount.is_finite():
            raise ValueError("Money amount must be a finite decimal value.")
        if _decimal_places(self.amount) > 3:
            raise ValueError("Anis amounts have at most three decimal places")
        try:
            with localcontext() as context:
                context.prec = _DECIMAL_PRECISION
                amount = self.amount.quantize(_SCALE)
        except InvalidOperation:
            raise ValueError("Money amount is outside the supported decimal range.") from None
        if amount.is_zero():
            amount = amount.copy_abs()
        object.__setattr__(self, "amount", amount)
        if self.as_of is not None:
            parsed = timestamp(self.as_of)
            if parsed is None:
                raise ValueError("Money as_of must be an aware datetime.")
            object.__setattr__(self, "as_of", parsed)

    @classmethod
    def from_json(cls, data: object) -> "Money":
        """Read decimal text only; accepting a JSON number can already lose price precision."""
        value = object_data(data)
        amount = field(value, "amount")
        if not isinstance(amount, str):
            raise ValueError("Money amount must be a decimal string, never a JSON number.")
        if not _AMOUNT_TEXT.fullmatch(amount):
            raise ValueError("Money amount must be plain decimal text.")
        try:
            decimal_amount = Decimal(amount)
        except (InvalidOperation, ValueError):
            raise ValueError("Money amount must be valid decimal text.") from None
        if not decimal_amount.is_finite():
            raise ValueError("Money amount must be a finite decimal value.")
        if _decimal_places(decimal_amount) > 3:
            raise ValueError(_AMOUNT_ERROR)
        if amount.startswith("-") and decimal_amount.is_zero():
            raise ValueError("Negative zero is not a valid Anis amount.")
        currency = text(field(value, "currency"), "")
        return cls(decimal_amount, currency or "", timestamp(field(value, "asOf")))

    def multiply(self, quantity: int) -> "Money":
        """Multiply exactly by a whole quantity and clear the old price observation time."""
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise TypeError("Money can only be multiplied by an integer quantity.")
        try:
            with localcontext() as context:
                context.prec = _DECIMAL_PRECISION
                amount = self.amount * quantity
        except InvalidOperation:
            raise ValueError("Money amount is outside the supported decimal range.") from None
        return Money(amount, self.currency)

    def to_wire_amount(self) -> str:
        """Write exactly three fractional digits because the public contract compares decimal strings."""
        return format(self.amount, ".3f")

    def to_json(self) -> dict[str, object]:
        """Write the exact contract object and omit `asOf` when no observation time was supplied."""
        result: dict[str, object] = {"amount": self.to_wire_amount(), "currency": self.currency}
        if self.as_of is not None:
            result["asOf"] = wire_timestamp(self.as_of, seconds_only=True)
        return result

    def __str__(self) -> str:
        return f"{self.to_wire_amount()} {self.currency}"


def _decimal_places(value: Decimal) -> int:
    """Count source scale, including trailing zeroes, so over-precise inputs are refused rather than rounded."""
    exponent = value.as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0
