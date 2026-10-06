"""Safety code and thumbprint conformance against the released vectors."""

import json
from pathlib import Path
from typing import cast

import pytest

from anis_partners.enrollment.key_thumbprint import compute
from anis_partners.enrollment.safety_code import SafetyCode
from anis_partners.verification.partner_jwk import PartnerJwk
from tests.support.vectors import read_vector, vector_files


def test_safety_code_vector_file_count_is_four() -> None:
    """Fail if a safety-code vector is missing."""
    assert len(vector_files("safety-code", "SC")) == 4


@pytest.mark.parametrize("path", vector_files("safety-code", "SC"), ids=lambda path: Path(path).stem)
def test_safety_code_vector_has_expected_thumbprint_and_code(path: Path) -> None:
    """Check one safety-code vector's local key fingerprint and spoken code."""
    vector = read_vector(path)
    jwk = PartnerJwk(**vector["publicJwk"])
    thumbprint = compute(jwk)
    assert thumbprint == vector["thumbprint"]
    assert SafetyCode.from_thumbprint(thumbprint) == vector["expectedCode"]


@pytest.mark.parametrize("path", vector_files("safety-code", "SC"), ids=lambda path: Path(path).stem)
def test_safety_code_vector_entries_have_declared_match_results(path: Path) -> None:
    """Check one vector's full set of accepted and refused user entries."""
    vector = read_vector(path)
    assert vector["inputs"]
    for case in vector["inputs"]:
        assert SafetyCode.matches(case["entered"], vector["thumbprint"]) is case["matches"]


def test_safety_code_manifest_lists_exactly_the_vectors_on_disk() -> None:
    """Detect a stale manifest or a vector missing from the shipped corpus."""
    directory = Path(__file__).resolve().parents[1] / "vectors" / "safety-code"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    vector_ids = sorted(path.stem for path in vector_files("safety-code", "SC"))
    assert sorted(item["id"] for item in manifest["vectors"]) == vector_ids
    assert manifest["total"] == len(vector_ids)


@pytest.mark.parametrize("thumbprint", [None, "", "not-a-thumbprint", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="])
def test_only_a_thumbprint_has_a_safety_code(thumbprint: str | None) -> None:
    """Reject malformed fingerprints instead of showing staff a code for the wrong key."""
    with pytest.raises(ValueError, match="thumbprint"):
        SafetyCode.from_thumbprint(cast(str, thumbprint))
