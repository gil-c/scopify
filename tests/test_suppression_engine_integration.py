"""Integration tests: inline ``# scopify: ignore`` suppression and SC003
wired through :func:`scopify.engine.check_project` / :func:`check_source`.
"""
from __future__ import annotations

from pathlib import Path

from scopify.engine import build_index, check_project, check_source


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def test_inline_ignore_suppresses_cross_file_sc001(tmp_path: Path):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(tmp_path, "alpha/core.py",
           "from scopify import internal\n@internal\ndef _helper():\n    pass\n")
    _write(tmp_path, "beta/__init__.py", "")
    _write(tmp_path, "beta/user.py",
           "from alpha.core import _helper  # scopify: ignore[SC001]\n")
    assert check_project(tmp_path) == []
def test_inline_ignore_does_not_suppress_other_codes(tmp_path: Path):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(tmp_path, "alpha/core.py",
           "from scopify import internal\n@internal\ndef _helper():\n    pass\n")
    _write(tmp_path, "beta/__init__.py", "")
    _write(tmp_path, "beta/user.py",
           "from alpha.core import _helper  # scopify: ignore[SC002]\n")
    diagnostics = check_project(tmp_path)
    assert any(d.code == "SC001" for d in diagnostics)
def test_bare_inline_ignore_suppresses_sc003(tmp_path: Path):
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/mod.py",
           "from scopify import public\n\n@public  # scopify: ignore\ndef _secret():\n    pass\n")
    diagnostics = check_project(tmp_path)
    assert not any(d.code == "SC003" for d in diagnostics)
def test_check_project_reports_sc003_by_default(tmp_path: Path):
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/mod.py",
           "from scopify import public\n\n@public\ndef _secret():\n    pass\n")
    diagnostics = check_project(tmp_path)
    assert any(d.code == "SC003" for d in diagnostics)
def test_disabled_rules_can_turn_off_sc003(tmp_path: Path):
    _write(tmp_path, "scopify.toml", 'disabled_rules = ["SC003"]\n')
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/mod.py",
           "from scopify import public\n\n@public\ndef _secret():\n    pass\n")
    diagnostics = check_project(tmp_path)
    assert not any(d.code == "SC003" for d in diagnostics)


def test_check_source_respects_inline_ignore_on_live_buffer(tmp_path: Path):
    _write(tmp_path, "pkg/__init__.py", "")
    mod = tmp_path / "pkg" / "mod.py"
    mod.write_text("from scopify import public\n\n@public\ndef _secret():\n    pass\n")
    index = build_index(tmp_path)
    live_source = (
        "from scopify import public\n\n@public  # scopify: ignore[SC003]\ndef _secret():\n    pass\n"
    )
    diagnostics = check_source(index, mod, source=live_source)
    assert not any(d.code == "SC003" for d in diagnostics)
def test_check_source_updates_sources_by_module_for_suppression(tmp_path: Path):
    _write(tmp_path, "pkg/__init__.py", "")
    mod = tmp_path / "pkg" / "mod.py"
    mod.write_text("from scopify import public\n\n@public\ndef _secret():\n    pass\n")
    index = build_index(tmp_path)
    assert any(d.code == "SC003" for d in check_source(index, mod, source=mod.read_text()))
    live_source = (
        "from scopify import public\n\n@public  # scopify: ignore[SC003]\ndef _secret():\n    pass\n"
    )
    check_source(index, mod, source=live_source)
    assert index.sources_by_module["pkg.mod"] == live_source
