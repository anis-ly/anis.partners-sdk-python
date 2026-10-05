"""Public request models require every wire value callers must deliberately supply."""

from inspect import Parameter, signature
from typing import Protocol, cast

import pytest

from anis_partners.models import CreateOrderRequest, EnrollmentKeyRequest, EnrollmentProofRequest


class _FromJson(Protocol):
    @classmethod
    def from_json(cls, data: object) -> object: ...


@pytest.mark.parametrize(
    ("model", "required"),
    [
        (CreateOrderRequest, ("card_id", "quantity", "expected_unit_price", "expected_total")),
        (EnrollmentKeyRequest, ("public_jwk", "not_before", "expires_at")),
        (EnrollmentProofRequest, ("key_id", "challenge_generation", "signature")),
    ],
)
def test_request_constructor_requires_each_required_value(model: type[object], required: tuple[str, ...]) -> None:
    """Prevent placeholder UUIDs, amounts, generations, or signatures from appearing optional to Python callers."""
    parameters = signature(model).parameters
    assert all(parameters[name].default is Parameter.empty for name in required)


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (CreateOrderRequest, "{}"),
        (EnrollmentKeyRequest, "{}"),
        (EnrollmentProofRequest, "{}"),
    ],
)
def test_request_wire_reader_refuses_missing_required_values(model: type[object], data: str) -> None:
    """Reject incomplete request-shaped JSON instead of constructing an unusable zero-valued model."""
    reader = cast(_FromJson, model)
    with pytest.raises(ValueError, match="require"):
        reader.from_json(data)
