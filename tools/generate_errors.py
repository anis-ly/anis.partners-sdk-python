"""Generate Python's public error-code enum from the canonical error catalogue."""

import json
import re
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parent.parent
CATALOGUE = ROOT / "contracts" / "error-catalogue.json"
OUTPUT = ROOT / "src" / "anis_partners" / "errors" / "_codes.py"


class _Representation(TypedDict, total=False):
    publicCode: str
    publicDocumentation: bool
    retryable: bool


class _Catalogue(TypedDict):
    representations: list[_Representation]


def _member(code: str) -> str:
    """Use stable uppercase names while keeping the exact wire spelling as each value."""
    return re.sub(r"[^A-Z0-9]+", "_", code.upper()).strip("_")


def render(catalogue_path: Path = CATALOGUE) -> str:
    """Render the generated module in memory so a drift check can compare exact bytes."""
    catalogue = json.loads(catalogue_path.read_text(encoding="utf-8"))
    typed_catalogue = catalogue if isinstance(catalogue, dict) else {}
    representations = typed_catalogue.get("representations", [])
    if not isinstance(representations, list):
        raise ValueError("The error catalogue must contain a representations array.")
    public = {
        item["publicCode"]: item
        for item in representations
        if isinstance(item, dict)
        and item.get("publicDocumentation") is True
        and isinstance(item.get("publicCode"), str)
    }
    lines = [
        '"""GENERATED from contracts/error-catalogue.json; do not edit, run tools/generate_errors.py."""',
        "",
        "from enum import StrEnum",
        "",
        "",
        "class ErrorCode(StrEnum):",
        '    """Identify API refusals by stable wire code rather than localized copy."""',
        "",
        '    UNKNOWN = "unknown"',
    ]
    for code in sorted(public):
        lines.append(f'    {_member(code)} = "{code}"')
    retryable = sorted(code for code, item in public.items() if item.get("retryable") is True)
    lines.extend(["", "", "RETRYABLE_CODES: frozenset[ErrorCode] = frozenset(", "    {"])
    lines.extend(f"        ErrorCode.{_member(code)}," for code in retryable)
    lines.extend(["    }", ")", "", "", "_BY_WIRE: dict[str, ErrorCode] = {"])
    lines.extend(f'    "{code}": ErrorCode.{_member(code)},' for code in sorted(public))
    lines.extend(
        [
            "}",
            "",
            "",
            "def parse_error_code(raw_code: str | None) -> ErrorCode:",
            '    """Map an unknown future code safely so it is never assumed retryable."""',
            "    return _BY_WIRE.get(raw_code, ErrorCode.UNKNOWN) if raw_code is not None else ErrorCode.UNKNOWN",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(), encoding="utf-8")
    print(f"generated public error codes -> {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
