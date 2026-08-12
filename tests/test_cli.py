"""CLI smoke tests."""
from pathlib import Path

from scopify.cli import main


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def test_cli_returns_zero_on_clean_project(tmp_path: Path, capsys):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(tmp_path, "alpha/a.py", "x = 1\n")
    rc = main(["check", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "0 issue" in out or "no issues" in out.lower()


def test_cli_returns_nonzero_on_violation(tmp_path: Path, capsys):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import internal\n@internal\ndef helper():\n    pass\n",
    )
    _write(tmp_path, "beta/__init__.py", "")
    _write(tmp_path, "beta/user.py", "from alpha.core import helper\n")

    rc = main(["check", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc != 0
    assert "SC001" in out


def test_cli_disable_suppresses_rule(tmp_path: Path, capsys):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import internal\n@internal\ndef _helper():\n    pass\n",
    )
    _write(tmp_path, "beta/__init__.py", "")
    _write(tmp_path, "beta/user.py", "from alpha.core import _helper\n")

    rc = main(["check", str(tmp_path), "--disable", "SC001"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "SC001" not in out


def test_cli_default_visibility_internal_flags_unannotated(tmp_path: Path, capsys):
    # With internal default, an unannotated symbol imported cross-package is a violation.
    _write(tmp_path, "alpha/__init__.py", "")
    _write(tmp_path, "alpha/core.py", "def helper():\n    pass\n")
    _write(tmp_path, "beta/__init__.py", "")
    _write(tmp_path, "beta/user.py", "from alpha.core import helper\n")

    rc = main(["check", str(tmp_path), "--default-visibility", "internal"])
    out = capsys.readouterr().out
    assert rc != 0
    assert "SC001" in out


def test_cli_root_override(tmp_path: Path, capsys):
    # src/ layout: without --root the heuristic resolves wrong top-level packages.
    src = tmp_path / "src"
    _write(src, "alpha/__init__.py", "")
    _write(
        src,
        "alpha/core.py",
        "from scopify import internal\n@internal\ndef helper():\n    pass\n",
    )
    _write(src, "beta/__init__.py", "")
    _write(src, "beta/user.py", "from alpha.core import helper\n")

    rc = main(["check", str(src), "--root", "alpha", "--root", "beta"])
    out = capsys.readouterr().out
    assert rc != 0
    assert "SC001" in out

