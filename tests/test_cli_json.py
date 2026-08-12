"""CLI JSON output format."""
import json
from pathlib import Path

from scopify.cli import main


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def test_json_output_clean_project_is_empty_list(tmp_path: Path, capsys):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(tmp_path, "alpha/a.py", "x = 1\n")
    rc = main(["check", "--format", "json", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload == []


def test_json_output_reports_each_diagnostic(tmp_path: Path, capsys):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import internal\n@internal\ndef helper():\n    pass\n",
    )
    _write(tmp_path, "beta/__init__.py", "")
    _write(tmp_path, "beta/user.py", "from alpha.core import helper\n")

    rc = main(["check", "--format", "json", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc != 0
    payload = json.loads(out)
    assert isinstance(payload, list)
    assert len(payload) >= 1
    entry = payload[0]
    assert entry["code"] == "SC001"
    assert entry["severity"] in ("error", "warning")
    assert Path(entry["file"]).name == "user.py"
    assert isinstance(entry["line"], int) and entry["line"] >= 1
    assert isinstance(entry["column"], int) and entry["column"] >= 0
    assert "helper" in entry["message"]

