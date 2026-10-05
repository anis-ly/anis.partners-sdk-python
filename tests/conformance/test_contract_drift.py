"""Keep public Python models, errors, routes, and signature profiles pinned to the contracts."""

import json
from dataclasses import fields
from pathlib import Path

from anis_partners.errors import ErrorCode
from anis_partners.models import EnrollmentKeyResult
from anis_partners.operations import PARTNER_ROUTES
from anis_partners.signing.signature_profile import SignatureProfile
from tools.generate_errors import OUTPUT, render

_ROOT = Path(__file__).resolve().parents[2]


def _contract(name: str) -> dict[str, object]:
    value = json.loads((_ROOT / "contracts" / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_sdk_route_table_matches_published_surface_in_both_directions() -> None:
    """Catch both invented routes and published operations the SDK cannot reach."""
    openapi = _contract("partner-public-v1.json")
    paths = openapi["paths"]
    assert isinstance(paths, dict)
    published = {
        (method.upper(), path)
        for path, operations in paths.items()
        for method in operations
        if method in {"get", "post", "put", "patch", "delete"}
    }
    sdk = {(route.method, route.template) for route in PARTNER_ROUTES}
    assert sdk == published


def test_each_route_has_the_profile_assigned_by_the_contract() -> None:
    """Keep signing policy attached to the contract route instead of inferring it from its URL."""
    openapi = _contract("partner-public-v1.json")
    paths = openapi["paths"]
    assert isinstance(paths, dict)
    profile_by_kind = {
        "safeRead": SignatureProfile.SAFE_READ,
        "bodylessNonceMutation": SignatureProfile.BODYLESS_NONCE_MUTATION,
        "orderMutation": SignatureProfile.ORDER_MUTATION,
    }
    for path, operations in paths.items():
        for method, operation in operations.items():
            if not isinstance(operation, dict) or "x-anis-route" not in operation:
                continue
            route_info = operation["x-anis-route"]
            assert isinstance(route_info, dict)
            kind = route_info.get("requestKind")
            expected = profile_by_kind.get(kind) if isinstance(kind, str) else None
            actual = next(
                route for route in PARTNER_ROUTES if route.method == method.upper() and route.template == path
            )
            assert actual.profile is expected


def test_every_public_error_code_in_the_catalogue_is_known_to_the_sdk() -> None:
    """Fail when generated code constants and public catalogue representations drift apart."""
    catalogue = _contract("error-catalogue.json")
    representations = catalogue["representations"]
    assert isinstance(representations, list)
    documented = {
        entry["publicCode"]
        for entry in representations
        if isinstance(entry, dict) and entry.get("publicDocumentation") is True
    }
    known = {member.value for member in ErrorCode if member is not ErrorCode.UNKNOWN}
    assert known == documented


def test_key_submission_answer_model_has_exactly_the_published_members() -> None:
    """Keep a missing or extra key-answer member from silently changing enrollment behavior."""
    openapi = _contract("partner-public-v1.json")
    components = openapi["components"]
    assert isinstance(components, dict)
    schemas = components["schemas"]
    assert isinstance(schemas, dict)
    schema = schemas["EnrollmentKeyResult"]
    assert isinstance(schema, dict)
    properties = schema["properties"]
    assert isinstance(properties, dict)
    published = set(properties)
    modelled = {
        "".join(part if index == 0 else part.title() for index, part in enumerate(item.name.split("_")))
        for item in fields(EnrollmentKeyResult)
    }
    assert modelled == published
    assert "safetyCode" in published


def test_generated_error_codes_equal_the_generator_output() -> None:
    """Replace numeric enum history checks with exact generated-file parity for string codes."""
    assert OUTPUT.read_text(encoding="utf-8") == render()


def test_covered_component_profiles_match_the_contract_description() -> None:
    """Pin component order because a changed order makes both request sides sign different bytes."""
    assert SignatureProfile.SAFE_READ.components == ("@method", "@authority", "@path", "@query", "x-anis-date")
    assert SignatureProfile.BODYLESS_NONCE_MUTATION.components == (
        "@method",
        "@authority",
        "@path",
        "@query",
        "content-digest",
        "nonce",
        "x-anis-date",
    )
    assert SignatureProfile.ORDER_MUTATION.components == (
        "@method",
        "@authority",
        "@path",
        "@query",
        "content-digest",
        "nonce",
        "idempotency-key",
        "x-anis-date",
    )
