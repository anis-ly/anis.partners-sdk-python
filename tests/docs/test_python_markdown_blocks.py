"""Keep Python snippets in the README and user guides syntactically valid as they evolve."""

import re
import tempfile
from pathlib import Path

import pytest
from mypy import api as mypy_api

_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_BLOCK = re.compile(r"```python[^\n]*\n(.*?)```", re.DOTALL)
_MARKDOWN_FILES = (_ROOT / "README.md", *_ROOT.joinpath("docs").glob("*.md"))
_BLOCKS = [
    pytest.param(path, index, block, id=f"{path.relative_to(_ROOT)}-block-{index + 1}")
    for path in _MARKDOWN_FILES
    for index, block in enumerate(_PYTHON_BLOCK.findall(path.read_text(encoding="utf-8")))
]


@pytest.mark.parametrize(("path", "index", "source"), _BLOCKS)
def test_every_markdown_python_block_type_checks(
    path: Path, index: int, source: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Type-check every published block so SDK names and method calls cannot silently drift."""
    preamble = """
from typing import Any, Protocol

anis: Any
logger: Any
options: Any
signer: Any
key_id: Any
database: Any
wallet_id: Any
request: Any
outcome: Any
operation_id: Any
credential_store: Any
alert_support: Any
reveal_from_invoice: Any
schedule_resume: Any
close_without_charge: Any
mark_fulfillment_ready: Any
card: Any

class _HardwareService(Protocol):
    def sign_p256_sha256(self, key_id: str, data: bytes) -> bytes: ...

hardware_service: _HardwareService
"""
    with tempfile.TemporaryDirectory(prefix="markdown-python-", dir=_ROOT / "tests") as directory:
        source_path = Path(directory) / "snippet.py"
        source_path.write_text(preamble + "\n" + source, encoding="utf-8")
        monkeypatch.setenv("MYPYPATH", str(_ROOT / "src"))
        stdout, stderr, status = mypy_api.run(
            [
                "--strict",
                "--python-version",
                "3.11",
                "--follow-imports=silent",
                str(source_path),
            ]
        )
    assert status == 0, f"{path.relative_to(_ROOT)} Python block {index + 1}:\n{stdout}{stderr}"


def test_markdown_python_block_scan_finds_documented_examples() -> None:
    """Fail if markdown discovery stops finding the README and user-guide examples."""
    assert _BLOCKS
