"""Integration tests: dynamic-construct diagnostics surfaced through the engine."""
from __future__ import annotations

from pathlib import Path

from scopify.engine import build_index, check_project, check_source


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def test_check_project_reports_dynamic_diagnostics(tmp_path: Path):
    _write(tmp_path, "pkg/__init__.py", "")
    _write(
        tmp_path,
        "pkg/mod.py",
        "attr = 'x'\ngetattr(object(), attr)\neval('1 + 1')\n",
    )
    diagnostics = check_project(tmp_path)
    codes = {d.code for d in diagnostics}
    assert "SC010" in codes
    assert "SC011" in codes


def test_check_source_reports_dynamic_diagnostics_for_live_buffer(tmp_path: Path):
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/mod.py", "x = 1\n")
    index = build_index(tmp_path)
    diags = check_source(
        index,
        file_path=tmp_path / "pkg" / "mod.py",
        source="attr = 'x'\ngetattr(object(), attr)\n",
    )
    assert any(d.code == "SC010" for d in diags)


def test_check_source_clears_dynamic_diagnostic_once_fixed(tmp_path: Path):
    _write(tmp_path, "pkg/__init__.py", "")
    _write(
        tmp_path,
        "pkg/mod.py",
        "attr = 'x'\ngetattr(object(), attr)\n",
    )
    index = build_index(tmp_path)
    file_path = tmp_path / "pkg" / "mod.py"
    assert any(
        d.code == "SC010" for d in check_source(index, file_path=file_path, source=None)
    )
    fixed = check_source(index, file_path=file_path, source="getattr(object(), 'x')\n")
    assert not any(d.code == "SC010" for d in fixed)
