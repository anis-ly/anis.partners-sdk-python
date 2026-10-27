"""Keep public Python models, errors, routes, and signature profiles pinned to the contracts."""

import json
from dataclasses import fields
from pathlib import Path

from anis_partners.errors import HTTP_STATUS, RETRY_GUIDANCE, ErrorCode
from anis_partners.models import EnrollmentKeyResult
from anis_partners.operations import PARTNER_ROUTES
from anis_partners.signing.signature_profile import SignatureProfile
from tools.generate_errors import OUTPUT, render

_ROOT = Path(__file__).resolve().parents[2]


def _contract(name: str) -> dict[str, object]:
    value = json.loads((_ROOT / "contracts" / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


# The gateway publishes three application-network routes that are staging-only test endpoints. They are
# deliberately and permanently outside this SDK (CONTRACT §18.2). The comparison below fails if the gateway's
# set of such routes changes.
_STAGING_TEST_ONLY_ROUTES = {
    ("GET", "/v1/application/networks"),
    ("POST", "/v1/application/networks"),
    ("POST", "/v1/application/networks/remove"),
}
_PROFILES = {
    "safeRead": SignatureProfile.SAFE_READ,
    "bodylessNonceMutation": SignatureProfile.BODYLESS_NONCE_MUTATION,
    "orderMutation": SignatureProfile.ORDER_MUTATION,
}


def _published() -> dict[tuple[str, str], dict[str, object]]:
    """Read every operation's route extension from the byte-identical gateway contract."""
    paths = _contract("partner-public-v1.json")["paths"]
    assert isinstance(paths, dict)
    result: dict[tuple[str, str], dict[str, object]] = {}
    for path, operations in paths.items():
        for method, operation in operations.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                assert isinstance(operation, dict)
                route_info = operation.get("x-anis-route", {})
                assert isinstance(route_info, dict)
                result[(method.upper(), path)] = route_info
    return result


def test_sdk_route_table_matches_published_surface_in_both_directions() -> None:
    """Catch both invented routes and published operations the SDK cannot reach."""
    published = _published()
    sdk = {(route.method, route.template) for route in PARTNER_ROUTES}
    assert set(published) - sdk == _STAGING_TEST_ONLY_ROUTES
    assert sdk - set(published) == set()
    assert len(published) == 42
    assert len(PARTNER_ROUTES) == 39


def test_each_route_has_the_profile_assigned_by_the_contract() -> None:
    """Keep signing policy attached to the contract route instead of inferring it from its URL."""
    published = _published()
    for route in PARTNER_ROUTES:
        info = published[(route.method, route.template)]
        kind = info.get("requestKind")
        assert route.profile is (_PROFILES.get(kind) if isinstance(kind, str) else None)
        assert route.signs_response is info.get("signsResponse")


def test_product_routes_match_the_published_route_ids_scopes_and_wallet_binding() -> None:
    """Pin the 17 added routes to the gateway's stable id, scope, wallet binding and answer signing."""
    published = _published()
    added = [route for route in PARTNER_ROUTES if route.route_id is not None]
    assert len(added) == 17
    for route in added:
        info = published[(route.method, route.template)]
        assert info["routeId"] == route.route_id
        assert info.get("requiredScope") == route.scope
        assert info.get("walletBound") is route.wallet_bound
    assert sum(route.signs_response for route in added) == 8
    assert {route.scope for route in added} == {
        None,
        "meter_charges:create",
        "meter_charges:read",
        "direct_recharges:create",
        "direct_recharges:read",
    }


def test_published_surface_counts_pin_the_full_gateway_catalogue() -> None:
    """Count the whole contract so a route added or removed upstream is noticed."""
    published = _published()
    assert len(published) == 42
    assert sum(info.get("signsResponse") is True for info in published.values()) == 21
    assert sum(info.get("signsResponse") is False for info in published.values()) == 21


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


def test_known_error_codes_count_unique_public_codes() -> None:
    """Count unique public codes, not representation rows: purchase_not_allowed has two statuses."""
    assert len({member.value for member in ErrorCode if member is not ErrorCode.UNKNOWN}) == 48


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
    """Detect stale generated values without losing deterministic source formatting."""
    assert OUTPUT.read_text(encoding="utf-8") == render()


def test_generated_error_status_and_guidance_match_the_catalogue() -> None:
    """Give partners correct recovery context while detecting stale generated error metadata."""
    catalogue = _contract("error-catalogue.json")
    representations = catalogue["representations"]
    assert isinstance(representations, list)
    unique_entries = {
        entry["publicCode"]: entry
        for entry in representations
        if isinstance(entry, dict) and entry.get("publicDocumentation") is True
    }
    for entry in unique_entries.values():
        code = ErrorCode(entry["publicCode"])
        assert HTTP_STATUS[code] == entry["httpStatus"]
        assert RETRY_GUIDANCE[code] == entry["retryGuidance"]


def test_purchase_not_allowed_catalogue_collision_remains_visible() -> None:
    """Keep the contract's code/status conflict explicit instead of silently rewriting its source."""
    catalogue = _contract("error-catalogue.json")
    representations = catalogue["representations"]
    assert isinstance(representations, list)
    matches = [
        entry
        for entry in representations
        if isinstance(entry, dict)
        and entry.get("publicCode") == "purchase_not_allowed"
        and entry.get("publicDocumentation") is True
    ]
    assert [entry["httpStatus"] for entry in matches] == [403, 409]
    assert HTTP_STATUS[ErrorCode.PURCHASE_NOT_ALLOWED] == 409


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


def test_only_the_named_exclusions_are_marked_staging_only() -> None:
    paths = _contract("partner-public-v1.json")["paths"]
    assert isinstance(paths, dict)
    staging = {
        (method.upper(), path)
        for path, operations in paths.items()
        for method, operation in operations.items()
        if isinstance(operation, dict) and operation.get("x-anis-availability") == "staging-only"
    }
    assert staging == _STAGING_TEST_ONLY_ROUTES
    assert staging.isdisjoint((route.method, route.template) for route in PARTNER_ROUTES)
    for method, path in staging:
        description = paths[path][method.lower()]["description"]
        assert "Staging only — testing endpoints, not available in production" in description
        assert "بيئة الاختبار فقط — نقاط نهاية للاختبار، غير متاحة في الإنتاج" in description


def test_published_signing_key_purpose_is_optional_but_documented_as_emitted() -> None:
    components = _contract("partner-public-v1.json")["components"]
    assert isinstance(components, dict)
    schema = components["schemas"]["PublishedSigningKey"]
    assert "purpose" not in schema["required"]
    assert schema["properties"]["purpose"]["enum"] == ["answer", "webhook"]
    assert "the service always emits it" in schema["properties"]["purpose"]["description"]


def test_recipient_patch_acknowledgement_matches_published_schema() -> None:
    from anis_partners import DirectRechargeAccepted
    from tests.support.partner import OPERATION

    contract = _contract("partner-public-v1.json")
    paths = contract["paths"]
    components = contract["components"]
    assert isinstance(paths, dict)
    assert isinstance(components, dict)
    operation = paths["/v1/direct-recharges/{operationId}/recipient"]["patch"]
    assert "200" not in operation["responses"]
    response = operation["responses"]["202"]
    assert operation["x-anis-route"]["signsResponse"] is True
    assert response["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/DirectRechargeAccepted"}
    assert response["headers"]["Location"] == {"$ref": "#/components/headers/Location"}
    schema = components["schemas"]["DirectRechargeAccepted"]
    acknowledgement = DirectRechargeAccepted(OPERATION)
    assert set(acknowledgement.to_json()) == set(schema["required"]) == set(schema["properties"])
    assert acknowledgement.to_json() == {
        "operationId": str(OPERATION),
        "operationType": "directRecharge",
        "status": "processing",
    }
