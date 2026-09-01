"""Tests for project configuration (scopify.config)."""
from __future__ import annotations

from pathlib import Path

import pytest

from scopify.config import load_config, merge_cli_overrides
from scopify.markers import Visibility


def test_defaults_when_no_config_file_present(tmp_path: Path):
    config = load_config(tmp_path)
    assert config.default_visibility is Visibility.PUBLIC


def test_standalone_scopify_toml_sets_default_visibility(tmp_path: Path):
    (tmp_path / "scopify.toml").write_text('default_visibility = "internal"\n')
    config = load_config(tmp_path)
    assert config.default_visibility is Visibility.INTERNAL


def test_pyproject_tool_section_sets_default_visibility(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.scopify]\ndefault_visibility = \"internal\"\n"
    )
    config = load_config(tmp_path)
    assert config.default_visibility is Visibility.INTERNAL


def test_standalone_toml_takes_precedence_over_pyproject(tmp_path: Path):
    (tmp_path / "scopify.toml").write_text('default_visibility = "internal"\n')
    (tmp_path / "pyproject.toml").write_text(
        "[tool.scopify]\ndefault_visibility = \"public\"\n"
    )
    config = load_config(tmp_path)
    assert config.default_visibility is Visibility.INTERNAL


def test_pyproject_without_scopify_section_uses_defaults(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    config = load_config(tmp_path)
    assert config.default_visibility is Visibility.PUBLIC


def test_invalid_default_visibility_value_raises(tmp_path: Path):
    (tmp_path / "scopify.toml").write_text('default_visibility = "protected"\n')
    with pytest.raises(ValueError, match="default_visibility"):
        load_config(tmp_path)


def test_missing_default_visibility_key_uses_defaults(tmp_path: Path):
    (tmp_path / "scopify.toml").write_text('some_other_key = 1\n')
    config = load_config(tmp_path)
    assert config.default_visibility is Visibility.PUBLIC


def test_defaults_have_empty_roots_and_disabled_rules(tmp_path: Path):
    config = load_config(tmp_path)
    assert config.roots == ()
    assert config.disabled_rules == frozenset()


def test_standalone_scopify_toml_sets_roots_and_disabled_rules(tmp_path: Path):
    (tmp_path / "scopify.toml").write_text(
        'roots = ["src.pkgA", "src.pkgB"]\n'
        'disabled_rules = ["SC010", "SC011"]\n'
    )
    config = load_config(tmp_path)
    assert config.roots == ("src.pkgA", "src.pkgB")
    assert config.disabled_rules == frozenset({"SC010", "SC011"})


def test_pyproject_tool_section_sets_roots_and_disabled_rules(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.scopify]\n"
        'roots = ["alpha", "beta"]\n'
        'disabled_rules = ["SC002"]\n'
    )
    config = load_config(tmp_path)
    assert config.roots == ("alpha", "beta")
    assert config.disabled_rules == frozenset({"SC002"})


def test_standalone_toml_roots_take_precedence_over_pyproject(tmp_path: Path):
    (tmp_path / "scopify.toml").write_text('roots = ["a"]\n')
    (tmp_path / "pyproject.toml").write_text(
        "[tool.scopify]\nroots = [\"b\"]\n"
    )
    config = load_config(tmp_path)
    assert config.roots == ("a",)


def test_invalid_roots_type_raises(tmp_path: Path):
    (tmp_path / "scopify.toml").write_text('roots = "not-a-list"\n')
    with pytest.raises(ValueError, match="roots"):
        load_config(tmp_path)


def test_invalid_roots_element_type_raises(tmp_path: Path):
    (tmp_path / "scopify.toml").write_text('roots = ["ok", 1]\n')
    with pytest.raises(ValueError, match="roots"):
        load_config(tmp_path)


def test_invalid_disabled_rules_type_raises(tmp_path: Path):
    (tmp_path / "scopify.toml").write_text('disabled_rules = 42\n')
    with pytest.raises(ValueError, match="disabled_rules"):
        load_config(tmp_path)


# ---------------------------------------------------------------------------
# merge_cli_overrides
# ---------------------------------------------------------------------------

def test_merge_no_overrides_returns_same_values(tmp_path: Path):
    base = load_config(tmp_path)
    merged = merge_cli_overrides(base)
    assert merged == base


def test_merge_overrides_default_visibility(tmp_path: Path):
    base = load_config(tmp_path)  # default = PUBLIC
    merged = merge_cli_overrides(base, default_visibility="internal")
    assert merged.default_visibility is Visibility.INTERNAL


def test_merge_default_visibility_invalid_raises(tmp_path: Path):
    base = load_config(tmp_path)
    with pytest.raises(ValueError, match="--default-visibility"):
        merge_cli_overrides(base, default_visibility="protected")


def test_merge_overrides_roots(tmp_path: Path):
    base = load_config(tmp_path)
    merged = merge_cli_overrides(base, roots=["src.pkgA", "src.pkgB"])
    assert merged.roots == ("src.pkgA", "src.pkgB")


def test_merge_disable_accumulates_on_top_of_file_config(tmp_path: Path):
    (tmp_path / "scopify.toml").write_text('disabled_rules = ["SC010"]\n')
    base = load_config(tmp_path)
    merged = merge_cli_overrides(base, disable=["SC014"])
    assert merged.disabled_rules == frozenset({"SC010", "SC014"})


def test_merge_disable_empty_list_does_not_override(tmp_path: Path):
    (tmp_path / "scopify.toml").write_text('disabled_rules = ["SC010"]\n')
    base = load_config(tmp_path)
    merged = merge_cli_overrides(base, disable=[])
    assert merged.disabled_rules == frozenset({"SC010"})


def test_merge_file_visibility_preserved_when_no_cli_override(tmp_path: Path):
    (tmp_path / "scopify.toml").write_text('default_visibility = "internal"\n')
    base = load_config(tmp_path)
    merged = merge_cli_overrides(base)
    assert merged.default_visibility is Visibility.INTERNAL


def test_a_zone_declares_the_modules_it_owns_and_what_it_hands_out(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.scopify.zones.http]
modules = ["scrapy.http", "scrapy.http.*"]
exposes = ["Request", "Response"]

[tool.scopify.zones.settings]
modules = ["scrapy.settings.**"]
""",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.zones["http"].exposes == ("Request", "Response")
    assert config.zone_of("scrapy.http.request") == "http"
    assert config.zone_of("scrapy.settings.default.deep") == "settings"
    assert config.zone_of("scrapy.utils.python") is None


def test_the_most_precise_pattern_wins_when_two_zones_overlap(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.scopify.zones.everything]
modules = ["app.**"]

[tool.scopify.zones.web]
modules = ["app.web.**"]
""",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.zone_of("app.web.views") == "web"
    assert config.zone_of("app.core.models") == "everything"


def test_a_zone_that_claims_no_module_is_refused(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.scopify.zones.empty]\nexposes = ['Thing']\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="must list at least one module"):
        load_config(tmp_path)


def test_no_declared_zones_means_no_zones_at_all(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.scopify]\nroots = ['app']\n", encoding="utf-8"
    )
    config = load_config(tmp_path)
    assert config.zones == {}
    assert config.zone_of("app.anything") is None
