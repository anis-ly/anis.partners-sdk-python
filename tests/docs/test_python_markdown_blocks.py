"""Keep Python snippets in the README and user guides syntactically valid as they evolve."""

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_BLOCK = re.compile(r"```python[^\n]*\n(.*?)```", re.DOTALL)
_MARKDOWN_FILES = (_ROOT / "README.md", *_ROOT.joinpath("docs").glob("*.md"))
_BLOCKS = [
    pytest.param(path, index, block, id=f"{path.relative_to(_ROOT)}-block-{index + 1}")
    for path in _MARKDOWN_FILES
    for index, block in enumerate(_PYTHON_BLOCK.findall(path.read_text(encoding="utf-8")))
]


@pytest.mark.parametrize(("path", "index", "source"), _BLOCKS)
def test_every_markdown_python_block_compiles(path: Path, index: int, source: str) -> None:
    """Compile every published Python block so malformed async snippets are caught before release."""
    compile(source, f"{path.relative_to(_ROOT)}:python-block-{index + 1}", "exec")


def test_markdown_python_block_scan_finds_documented_examples() -> None:
    """Fail if markdown discovery stops finding the README and user-guide examples."""
    assert _BLOCKS
