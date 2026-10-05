"""Load the released .NET SDK conformance corpus copied into this repository."""

import json
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1] / "vectors"


def vector_files(kind: str, prefix: str) -> list[Path]:
    """Return ordered vector paths for one suite."""
    return sorted((ROOT / kind).glob(f"{prefix}-*.json"))


def read_vector(path: Path) -> dict[str, Any]:
    """Read one UTF-8 JSON fixture."""
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
