"""Load the released .NET SDK conformance corpus copied into this repository."""

import json
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1] / "vectors"


def vector_files(kind: str, prefix: str) -> list[Path]:
    """Return ordered vector paths for one suite."""
    directory = ROOT / kind
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        return sorted(directory.glob(f"{prefix}-*.json"))
    manifest = read_vector(manifest_path)
    if "vectors" not in manifest and "total" in manifest:
        paths = sorted(directory.glob(f"{prefix}-*.json"))
        if len(paths) != manifest["total"]:
            raise ValueError("The vector manifest count does not match the available files.")
        return paths
    entries = manifest["vectors"]
    paths = [
        directory / (entry if isinstance(entry, str) else (entry["file"] if "file" in entry else entry["id"] + ".json"))
        for entry in entries
    ]
    if any(not path.is_file() for path in paths):
        raise ValueError("The vector manifest lists missing files.")
    return sorted(paths)


def read_vector(path: Path) -> dict[str, Any]:
    """Read one UTF-8 JSON fixture."""
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
