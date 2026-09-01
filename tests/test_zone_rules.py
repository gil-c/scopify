"""Tests for SC020 / SC021 — declared zones versus the code on disk."""
from __future__ import annotations

from pathlib import Path

from scopify.engine import check_project

DECLARED = """
[tool.scopify.zones.core]
modules = ["app.core", "app.core.**"]
exposes = ["User"]

[tool.scopify.zones.root]
modules = ["app"]
"""


def write(root: Path, files: dict[str, str]) -> None:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def project(root: Path, *, config: str | None = None) -> None:
    write(
        root,
        {
            "app/__init__.py": "",
            "app/core/__init__.py": "",
            "app/core/models.py": "class User: pass\n",
        },
    )
    if config is not None:
        (root / "pyproject.toml").write_text(config, encoding="utf-8")


def codes(root: Path) -> list[str]:
    return [d.code for d in check_project(root)]


def test_no_declared_zones_means_the_rule_never_fires(tmp_path: Path) -> None:
    project(tmp_path, config="[tool.scopify]\nroots = ['app']\n")
    assert "SC020" not in codes(tmp_path)


def test_a_full_declaration_is_quiet(tmp_path: Path) -> None:
    project(tmp_path, config=DECLARED)
    assert "SC020" not in codes(tmp_path)
    assert "SC021" not in codes(tmp_path)


def test_a_package_no_zone_claims_is_reported_once_on_its_init(
    tmp_path: Path,
) -> None:
    project(tmp_path, config=DECLARED)
    write(
        tmp_path,
        {"app/web/__init__.py": "", "app/web/views.py": "", "app/web/forms.py": ""},
    )
    found = [d for d in check_project(tmp_path) if d.code == "SC020"]
    assert len(found) == 1
    assert found[0].file.name == "__init__.py"
    assert found[0].file.parent.name == "web"
    assert found[0].severity == "error"


def test_adding_a_folder_never_dirties_the_package_above_it(tmp_path: Path) -> None:
    project(tmp_path, config=DECLARED)
    write(tmp_path, {"app/web/__init__.py": "", "app/web/deep/__init__.py": ""})
    packages = {d.symbol for d in check_project(tmp_path) if d.code == "SC020"}
    assert packages == {"app.web", "app.web.deep"}
    assert "app" not in packages


def test_a_zone_matching_nothing_is_reported_on_the_config_file(
    tmp_path: Path,
) -> None:
    project(
        tmp_path,
        config=DECLARED + '\n[tool.scopify.zones.gone]\nmodules = ["app.gone.**"]\n',
    )
    found = [d for d in check_project(tmp_path) if d.code == "SC021"]
    assert len(found) == 1
    assert found[0].file.name == "pyproject.toml"
    assert found[0].symbol == "gone"
    assert found[0].severity == "warning"


def test_the_generated_declaration_leaves_no_package_unclaimed(
    tmp_path: Path,
) -> None:
    """The round-trip that makes the format trustworthy."""
    from scopify.zones import analyse, format_config

    project(tmp_path)
    write(tmp_path, {"app/web/__init__.py": "", "app/web/views.py": ""})
    (tmp_path / "pyproject.toml").write_text(
        format_config(analyse(tmp_path)), encoding="utf-8"
    )
    assert [d for d in check_project(tmp_path) if d.code in ("SC020", "SC021")] == []
