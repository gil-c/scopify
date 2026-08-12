"""End-to-end tests: config-driven roots/disabled_rules and attribute usages
(not just `from X import Y`) reaching SC001/SC002."""
from pathlib import Path

from scopify.engine import check_project


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def test_class_member_internal_usage_via_instance_is_flagged_cross_package(tmp_path: Path):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import internal\n"
        "class Widget:\n"
        "    @internal\n"
        "    def helper(self):\n"
        "        pass\n",
    )
    _write(tmp_path, "beta/__init__.py", "")
    _write(
        tmp_path,
        "beta/user.py",
        "from alpha.core import Widget\nw = Widget()\nw.helper()\n",
    )

    diagnostics = check_project(tmp_path)
    codes = [d.code for d in diagnostics]
    assert "SC001" in codes


def test_class_member_internal_usage_via_instance_is_allowed_same_package(tmp_path: Path):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import internal\n"
        "class Widget:\n"
        "    @internal\n"
        "    def helper(self):\n"
        "        pass\n",
    )
    _write(
        tmp_path,
        "alpha/user.py",
        "from alpha.core import Widget\nw = Widget()\nw.helper()\n",
    )

    diagnostics = check_project(tmp_path)
    assert [d for d in diagnostics if d.code == "SC001"] == []


def test_bare_module_import_qualified_attribute_usage_is_flagged(tmp_path: Path):
    # `import alpha.core; alpha.core.helper()` bypasses `from X import Y`
    # entirely; SC001 must still see it.
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import internal\n@internal\ndef helper():\n    pass\n",
    )
    _write(tmp_path, "beta/__init__.py", "")
    _write(tmp_path, "beta/user.py", "import alpha.core\nalpha.core.helper()\n")

    diagnostics = check_project(tmp_path)
    assert "SC001" in [d.code for d in diagnostics]


def test_roots_config_separates_packages_under_shared_src_layout(tmp_path: Path):
    # Without `roots`, both packages share the "src" first segment and would
    # be wrongly treated as the same top-level package.
    _write(tmp_path, "scopify.toml", 'roots = ["src.pkgA", "src.pkgB"]\n')
    _write(tmp_path, "src/pkgA/__init__.py", "")
    _write(
        tmp_path,
        "src/pkgA/core.py",
        "from scopify import internal\n@internal\ndef helper():\n    pass\n",
    )
    _write(tmp_path, "src/pkgB/__init__.py", "")
    _write(tmp_path, "src/pkgB/user.py", "from src.pkgA.core import helper\n")

    diagnostics = check_project(tmp_path)
    assert "SC001" in [d.code for d in diagnostics]


def test_disabled_rules_config_suppresses_matching_diagnostics(tmp_path: Path):
    _write(tmp_path, "scopify.toml", 'disabled_rules = ["SC001"]\n')
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import internal\n@internal\ndef _helper():\n    pass\n",
    )
    _write(tmp_path, "beta/__init__.py", "")
    _write(tmp_path, "beta/user.py", "from alpha.core import _helper\n")

    diagnostics = check_project(tmp_path)
    assert diagnostics == []
