"""Tests for per-rule severity configuration (Phase A — D6)."""
from __future__ import annotations

from pathlib import Path

import pytest

from scopify.config import ScopifyConfig, load_config
from scopify.engine import check_project

# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


def test_defaults_have_empty_severity(tmp_path: Path):
    config = load_config(tmp_path)
    assert config.severity == {}


def test_severity_parsed_from_scopify_toml(tmp_path: Path):
    (tmp_path / "scopify.toml").write_text(
        "[severity]\n"
        'SC017 = "warning"\n'
        'SC003 = "hint"\n'
    )
    config = load_config(tmp_path)
    assert config.severity == {"SC017": "warning", "SC003": "hint"}


def test_severity_parsed_from_pyproject_toml(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.scopify.severity]\n"
        'SC011 = "warning"\n'
    )
    config = load_config(tmp_path)
    assert config.severity == {"SC011": "warning"}


def test_severity_none_is_valid(tmp_path: Path):
    (tmp_path / "scopify.toml").write_text('[severity]\nSC010 = "none"\n')
    config = load_config(tmp_path)
    assert config.severity == {"SC010": "none"}


def test_severity_invalid_level_raises(tmp_path: Path):
    (tmp_path / "scopify.toml").write_text('[severity]\nSC010 = "critical"\n')
    with pytest.raises(ValueError, match="severity"):
        load_config(tmp_path)


def test_severity_not_a_table_raises(tmp_path: Path):
    (tmp_path / "scopify.toml").write_text('severity = ["SC010"]\n')
    with pytest.raises(ValueError, match="severity"):
        load_config(tmp_path)


def test_severity_all_valid_levels(tmp_path: Path):
    (tmp_path / "scopify.toml").write_text(
        "[severity]\n"
        'SC010 = "error"\n'
        'SC011 = "warning"\n'
        'SC012 = "hint"\n'
        'SC013 = "none"\n'
    )
    config = load_config(tmp_path)
    assert config.severity == {
        "SC010": "error",
        "SC011": "warning",
        "SC012": "hint",
        "SC013": "none",
    }


# ---------------------------------------------------------------------------
# Engine: severity overrides applied to diagnostics
# ---------------------------------------------------------------------------


def _make_project(tmp_path: Path, src: str) -> Path:
    """Minimal project with a single module that triggers SC003."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text(src)
    return tmp_path


def test_severity_override_changes_diagnostic_severity(tmp_path: Path):
    """SC003 is 'warning' by default for @internal on non-underscore name.
    Overriding it to 'error' should be reflected on the diagnostic."""
    _make_project(
        tmp_path,
        "from scopify import internal\n\n@internal\ndef my_func(): pass\n",
    )
    config = ScopifyConfig(severity={"SC003": "error"})
    diags = check_project(tmp_path, config=config)
    sc003 = [d for d in diags if d.code == "SC003"]
    assert sc003, "Expected at least one SC003 diagnostic"
    assert all(d.severity == "error" for d in sc003)


def test_severity_override_hint(tmp_path: Path):
    _make_project(
        tmp_path,
        "from scopify import internal\n\n@internal\ndef my_func(): pass\n",
    )
    config = ScopifyConfig(severity={"SC003": "hint"})
    diags = check_project(tmp_path, config=config)
    sc003 = [d for d in diags if d.code == "SC003"]
    assert sc003
    assert all(d.severity == "hint" for d in sc003)


def test_severity_none_silences_rule(tmp_path: Path):
    """severity = 'none' should suppress diagnostics for that rule entirely."""
    _make_project(
        tmp_path,
        "from scopify import internal\n\n@internal\ndef my_func(): pass\n",
    )
    config = ScopifyConfig(severity={"SC003": "none"})
    diags = check_project(tmp_path, config=config)
    assert not any(d.code == "SC003" for d in diags)


def test_severity_none_equivalent_to_disabled_rules(tmp_path: Path):
    """Both severity='none' and disabled_rules should produce identical results."""
    src = "from scopify import internal\n\n@internal\ndef my_func(): pass\n"
    _make_project(tmp_path, src)

    via_severity = check_project(tmp_path, config=ScopifyConfig(severity={"SC003": "none"}))
    via_disabled = check_project(tmp_path, config=ScopifyConfig(disabled_rules=frozenset({"SC003"})))

    codes_sev = {d.code for d in via_severity}
    codes_dis = {d.code for d in via_disabled}
    assert codes_sev == codes_dis


def test_severity_override_loaded_from_config_file(tmp_path: Path):
    """End-to-end: severity override from scopify.toml reaches diagnostics."""
    _make_project(
        tmp_path,
        "from scopify import internal\n\n@internal\ndef my_func(): pass\n",
    )
    (tmp_path / "scopify.toml").write_text('[severity]\nSC003 = "hint"\n')
    diags = check_project(tmp_path)  # loads config from disk
    sc003 = [d for d in diags if d.code == "SC003"]
    assert sc003
    assert all(d.severity == "hint" for d in sc003)


def test_unoverridden_rules_keep_default_severity(tmp_path: Path):
    """Rules not listed in severity keep their built-in default."""
    _make_project(
        tmp_path,
        "from scopify import internal\n\n@internal\ndef my_func(): pass\n",
    )
    config = ScopifyConfig(severity={"SC001": "warning"})  # SC003 not overridden
    diags = check_project(tmp_path, config=config)
    sc003 = [d for d in diags if d.code == "SC003"]
    assert sc003
    # SC003 default severity for @internal-without-underscore is "warning"
    assert all(d.severity == "warning" for d in sc003)
