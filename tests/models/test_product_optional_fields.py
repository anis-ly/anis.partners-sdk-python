"""Exercise optional members from the published schemas, including future additions."""

import copy
import json
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

import anis_partners as sdk
from anis_partners.models._json import camel_case

SCHEMAS: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/partner-public-v1.json").read_text()
)["components"]["schemas"]
MODULES = {
    sdk.models.direct_recharge_products.__name__,
    sdk.models.direct_recharges.__name__,
    sdk.models.meter_charges.__name__,
    sdk.models.webhooks.__name__,
}
MODELS = {
    name: getattr(sdk, name)
    for name, schema in SCHEMAS.items()
    if schema.get("properties") and getattr(getattr(sdk, name, None), "__module__", None) in MODULES
}
CASES = [
    (name, member)
    for name in MODELS
    for member in SCHEMAS[name]["properties"]
    if member not in SCHEMAS[name].get("required", [])
]


def example(schema: dict[str, Any], member: str = "") -> Any:
    if "$ref" in schema:
        return example(SCHEMAS[schema["$ref"].rsplit("/", 1)[1]], member)
    if "allOf" in schema:
        return example(schema["allOf"][0], member)
    if "enum" in schema:
        return schema["enum"][0]
    if "properties" in schema:
        return {key: example(value, key) for key, value in schema["properties"].items()}
    if schema.get("type") == "array":
        return [example(schema["items"])]
    if schema.get("type") == "boolean":
        return False
    if schema.get("type") == "integer":
        return 1
    if schema.get("format") == "uuid" or member.endswith("Id") or member == "id":
        return "9b2d1241-413e-4ae8-ae32-b15c58dbe101"
    if schema.get("format") == "date-time":
        return "2026-10-20T08:00:00Z"
    if member in {"amount", "payoutAmount", "minimumPayout", "maximumPayout"}:
        return "1.000"
    if member == "exchangeRate":
        return "0.155000"
    if member == "currency":
        return "LYD"
    if schema.get("type") == "object":
        return {}
    return "example"


def test_schema_optional_coverage_includes_every_new_object_model() -> None:
    assert len(MODELS) >= 30
    assert {"DirectRechargeLimits", "MeterReceipt", "DirectRechargeRecipientValue"} <= MODELS.keys()
    assert len(CASES) >= 50


@pytest.mark.parametrize(("name", "member"), CASES, ids=[f"{n}.{m}" for n, m in CASES])
@pytest.mark.parametrize("null", [False, True], ids=["omitted", "null"])
def test_every_schema_optional_member_remains_absent(name: str, member: str, null: bool) -> None:
    data = example(SCHEMAS[name])
    # Validate the complete shape first; deleting a field must not hide a broken fixture.
    expected = MODELS[name].from_json(copy.deepcopy(data)).to_json()
    expected.pop(member, None)
    if null:
        data[member] = None
    else:
        del data[member]
    model = MODELS[name].from_json(data)
    attribute = next(item.name for item in fields(model) if camel_case(item.name).rstrip("_") == member)
    assert getattr(model, attribute) is None
    assert member not in model.to_json()
    assert model.to_json() == expected
