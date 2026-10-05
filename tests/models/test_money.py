"""Exact decimal serialization and arithmetic checks for wire money."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import pytest

from anis_partners.models.money import Money


def test_money_parses_and_writes_three_decimal_places() -> None:
    """Preserve exact decimal text and UTC as-of seconds on the wire."""
    value = Money.from_json('{"amount":"10.5","currency":"LYD","asOf":"2026-09-19T08:00:00+02:00"}')
    assert value.amount == Decimal("10.500")
    assert value.to_json() == {"amount": "10.500", "currency": "LYD", "asOf": "2026-09-19T06:00:00Z"}


def test_money_refuses_a_json_number() -> None:
    """Refuse JSON numbers before binary floating-point precision can change a price."""
    with pytest.raises(ValueError, match="decimal string"):
        Money.from_json('{"amount":10.5,"currency":"LYD"}')


def test_money_refuses_a_float_constructor_value() -> None:
    """Prevent binary floating-point values entering exact order arithmetic."""
    with pytest.raises(TypeError, match="float"):
        Money(cast(Decimal, 10.5), "LYD")


def test_money_multiplies_exactly_and_clears_as_of() -> None:
    """Multiply Decimal values exactly without retaining a stale catalogue observation time."""
    value = Money(Decimal("10.500"), "LYD", datetime(2026, 9, 19, 8, tzinfo=UTC)).multiply(3)
    assert value.amount == Decimal("31.500")
    assert value.as_of is None


def test_money_refuses_more_than_three_decimal_places_in_the_constructor() -> None:
    """Reject excess precision before serialization so a price can never be silently rounded."""
    with pytest.raises(ValueError, match="Anis amounts have at most three decimal places"):
        Money(Decimal("0.0004"), "LYD")


def test_money_refuses_more_than_three_decimal_places_on_the_wire() -> None:
    """Reject a contract-breaching price rather than normalizing it into another amount."""
    with pytest.raises(ValueError, match="Anis amounts have at most three decimal places"):
        Money.from_json('{"amount":"0.0004","currency":"LYD"}')


def test_money_accepts_negative_amounts_for_order_guards_to_reject_as_prices() -> None:
    """Keep Money general while the order boundary rejects non-positive unit prices before sending."""
    assert Money(Decimal("-0.001"), "LYD").to_wire_amount() == "-0.001"


def test_money_pads_allowed_scale_without_rounding() -> None:
    """Pad legal precision for the wire while leaving the represented amount unchanged."""
    assert Money(Decimal("10.5"), "LYD").to_wire_amount() == "10.500"
