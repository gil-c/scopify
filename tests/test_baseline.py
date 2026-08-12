"""Tests for baseline mode (Phase A — --write-baseline / --baseline)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scopify.baseline import filter_new, load_baseline, write_baseline
from scopify.cli import main
from scopify.diagnostics import Diagnostic

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _violation_project(root: Path) -> None:
    """Minimal project that produces one SC001 violation."""
    _write(root, "alpha/__init__.py", "")
    _write(
        root,
        "alpha/core.py",
        "from scopify import internal\n\n@internal\ndef helper(): pass\n",
    )
    _write(root, "beta/__init__.py", "")
    _write(root, "beta/user.py", "from alpha.core import helper\n")


def _make_diag(file: Path, code: str = "SC001", line: int = 1, col: int = 0) -> Diagnostic:
    return Diagnostic(code=code, message="test", file=file, line=line, column=col)


# ---------------------------------------------------------------------------
# baseline.py unit tests
# ---------------------------------------------------------------------------


def test_write_and_load_roundtrip(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    f = root / "mod.py"
    f.touch()
    diag = _make_diag(f)
    baseline_file = tmp_path / "baseline.json"

    write_baseline([diag], root, baseline_file)

    assert baseline_file.is_file()
    entries = load_baseline(baseline_file)
    assert ("mod.py", "SC001", 1, 0) in entries


def test_write_baseline_json_structure(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    f = root / "sub" / "mod.py"
    f.parent.mkdir()
    f.touch()
    diag = _make_diag(f, code="SC017", line=5, col=3)
    baseline_file = tmp_path / "b.json"

    write_baseline([diag], root, baseline_file)

    data = json.loads(baseline_file.read_text())
    assert data["version"] == 1
    assert data["entries"] == [{"file": "sub/mod.py", "code": "SC017", "line": 5, "col": 3}]


def test_write_baseline_empty_project(tmp_path: Path):
    root = tmp_path
    baseline_file = tmp_path / "b.json"
    write_baseline([], root, baseline_file)
    entries = load_baseline(baseline_file)
    assert entries == frozenset()


def test_load_baseline_wrong_version_raises(tmp_path: Path):
    f = tmp_path / "b.json"
    f.write_text(json.dumps({"version": 99, "entries": []}))
    with pytest.raises(ValueError, match="version"):
        load_baseline(f)


def test_filter_new_removes_baseline_matches(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    f = root / "mod.py"
    f.touch()
    diag = _make_diag(f, line=1, col=0)
    baseline = frozenset({("mod.py", "SC001", 1, 0)})
    result = filter_new([diag], root, baseline)
    assert result == []


def test_filter_new_keeps_unmatched_violations(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    f = root / "mod.py"
    f.touch()
    old_diag = _make_diag(f, line=1, col=0)
    new_diag = _make_diag(f, line=10, col=0)
    baseline = frozenset({("mod.py", "SC001", 1, 0)})
    result = filter_new([old_diag, new_diag], root, baseline)
    assert result == [new_diag]


def test_filter_new_different_code_is_new(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    f = root / "mod.py"
    f.touch()
    diag = _make_diag(f, code="SC002", line=1, col=0)
    baseline = frozenset({("mod.py", "SC001", 1, 0)})  # different code
    result = filter_new([diag], root, baseline)
    assert result == [diag]


def test_filter_new_empty_baseline_keeps_all(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    f = root / "mod.py"
    f.touch()
    diag = _make_diag(f)
    result = filter_new([diag], root, frozenset())
    assert result == [diag]


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


def test_cli_write_baseline_creates_file(tmp_path: Path, capsys):
    _violation_project(tmp_path)
    baseline_file = tmp_path / "baseline.json"

    rc = main(["check", str(tmp_path), "--write-baseline", str(baseline_file)])
    out = capsys.readouterr().out

    assert rc == 0
    assert baseline_file.is_file()
    assert "baseline written" in out


def test_cli_write_baseline_default_filename(tmp_path: Path, capsys):
    _violation_project(tmp_path)
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        rc = main(["check", str(tmp_path), "--write-baseline"])
        assert rc == 0
        assert (tmp_path / "scopify-baseline.json").is_file()
    finally:
        os.chdir(old_cwd)


def test_cli_write_baseline_exits_zero_even_with_violations(tmp_path: Path, capsys):
    _violation_project(tmp_path)
    rc = main(["check", str(tmp_path), "--write-baseline", str(tmp_path / "b.json")])
    assert rc == 0


def test_cli_baseline_suppresses_known_violations(tmp_path: Path, capsys):
    _violation_project(tmp_path)
    baseline_file = tmp_path / "b.json"

    # Write baseline with all current violations
    main(["check", str(tmp_path), "--write-baseline", str(baseline_file)])
    capsys.readouterr()  # discard output

    # Now check with baseline: no new violations → exit 0
    rc = main(["check", str(tmp_path), "--baseline", str(baseline_file)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "0 issue" in out


def test_cli_baseline_reports_new_violations(tmp_path: Path, capsys):
    _violation_project(tmp_path)
    baseline_file = tmp_path / "b.json"

    # Write baseline (captures the SC001)
    main(["check", str(tmp_path), "--write-baseline", str(baseline_file)])
    capsys.readouterr()

    # Add a second violation in a new file
    _write(
        tmp_path,
        "gamma/__init__.py",
        "",
    )
    _write(
        tmp_path,
        "gamma/new.py",
        "from alpha.core import helper\n",  # another SC001
    )

    rc = main(["check", str(tmp_path), "--baseline", str(baseline_file)])
    out = capsys.readouterr().out
    assert rc != 0
    assert "SC001" in out


def test_cli_baseline_file_not_found_returns_2(tmp_path: Path, capsys):
    _violation_project(tmp_path)
    rc = main(["check", str(tmp_path), "--baseline", str(tmp_path / "nonexistent.json")])
    assert rc == 2


def test_cli_baseline_bad_version_returns_2(tmp_path: Path, capsys):
    _violation_project(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"version": 42, "entries": []}))
    rc = main(["check", str(tmp_path), "--baseline", str(bad)])
    assert rc == 2


def test_cli_write_baseline_json_format(tmp_path: Path, capsys):
    """--write-baseline + --format json should still write the baseline and exit 0."""
    _violation_project(tmp_path)
    baseline_file = tmp_path / "b.json"
    rc = main([
        "check", str(tmp_path),
        "--write-baseline", str(baseline_file),
        "--format", "json",
    ])
    assert rc == 0
    assert baseline_file.is_file()


def test_cli_baseline_json_output(tmp_path: Path, capsys):
    """--baseline with --format json outputs only new violations as JSON."""
    _violation_project(tmp_path)
    baseline_file = tmp_path / "b.json"
    main(["check", str(tmp_path), "--write-baseline", str(baseline_file)])
    capsys.readouterr()

    # No new violations; JSON output should be empty array
    rc = main(["check", str(tmp_path), "--baseline", str(baseline_file), "--format", "json"])
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out) == []
