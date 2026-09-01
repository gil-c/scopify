"""Tests for the published API surface: doors (``scopify.exports``) and
their enforcement (SC004 / SC005)."""
from __future__ import annotations

from pathlib import Path

from scopify.engine import check_project
from scopify.exports import collect_explicit_reexports, collect_exports, door_of

# ---------------------------------------------------------------------------
# Declaration parsing
# ---------------------------------------------------------------------------


def test_collect_exports_returns_none_without_declaration():
    assert collect_exports("x = 1\n") is None


def test_collect_exports_distinguishes_empty_from_absent():
    assert collect_exports("__all__ = []\n") == frozenset()


def test_collect_exports_reads_list_and_tuple():
    assert collect_exports("__all__ = ['a', 'b']") == {"a", "b"}
    assert collect_exports("__all__ = ('a',)") == {"a"}


def test_collect_exports_accumulates_augmented_forms():
    source = """
__all__ = ["a"]
__all__ += ["b"]
__all__.extend(["c"])
__all__.append("d")
"""
    assert collect_exports(source) == {"a", "b", "c", "d"}


def test_collect_exports_handles_concatenation():
    assert collect_exports("__all__ = ['a'] + ['b']") == {"a", "b"}


def test_collect_exports_skips_non_literal_entries():
    assert collect_exports("__all__ = ['a', SOME_NAME]") == {"a"}


def test_collect_exports_survives_syntax_error():
    assert collect_exports("def broken(:\n") is None


def test_explicit_reexports_require_the_redundant_alias():
    source = """
from .app import Flask as Flask
from .helpers import quiet
from . import json as json
"""
    assert collect_explicit_reexports(source) == {"Flask", "json"}


def test_door_of_prefers_all_over_redundant_aliases():
    source = """
from .app import Flask as Flask
__all__ = ["Only"]
"""
    assert door_of(source) == {"Only"}


def test_door_of_returns_none_when_nothing_is_published():
    assert door_of("from .app import Flask\n") is None


# ---------------------------------------------------------------------------
# SC004 — reaching past a door
# ---------------------------------------------------------------------------


def _write(root: Path, files: dict[str, str]) -> None:
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def _codes(root: Path) -> list[str]:
    return [d.code for d in check_project(root)]


def test_sc004_flags_import_of_an_unpublished_name(tmp_path: Path):
    _write(
        tmp_path,
        {
            "lib/__init__.py": "from .core import Client\n__all__ = ['Client']\n",
            "lib/core.py": "class Client: ...\ndef plumbing(): ...\n",
            "app/__init__.py": "",
            "app/main.py": "from lib.core import plumbing\n",
        },
    )
    diagnostics = [d for d in check_project(tmp_path) if d.code == "SC004"]
    assert len(diagnostics) == 1
    assert diagnostics[0].symbol == "plumbing"
    assert diagnostics[0].severity == "warning"


def test_sc004_allows_a_published_name(tmp_path: Path):
    _write(
        tmp_path,
        {
            "lib/__init__.py": "from .core import Client\n__all__ = ['Client']\n",
            "lib/core.py": "class Client: ...\n",
            "app/__init__.py": "",
            "app/main.py": "from lib import Client\n",
        },
    )
    assert "SC004" not in _codes(tmp_path)


def test_sc004_ignores_imports_from_inside_the_package(tmp_path: Path):
    _write(
        tmp_path,
        {
            "lib/__init__.py": "from .core import Client\n__all__ = ['Client']\n",
            "lib/core.py": "class Client: ...\ndef plumbing(): ...\n",
            "lib/other.py": "from lib.core import plumbing\n",
        },
    )
    assert "SC004" not in _codes(tmp_path)


def test_sc004_reports_the_innermost_crossed_door(tmp_path: Path):
    _write(
        tmp_path,
        {
            "lib/__init__.py": "__all__ = ['Client']\nfrom .sub import Client\n",
            "lib/sub/__init__.py": "from .core import Client\n__all__ = ['Client']\n",
            "lib/sub/core.py": "class Client: ...\ndef plumbing(): ...\n",
            "lib/other.py": "from lib.sub.core import plumbing\n",
        },
    )
    diagnostics = [d for d in check_project(tmp_path) if d.code == "SC004"]
    assert len(diagnostics) == 1
    assert "'lib.sub'" in diagnostics[0].message


def test_sc004_ignores_submodule_imports(tmp_path: Path):
    _write(
        tmp_path,
        {
            "lib/__init__.py": "__all__ = ['Client']\nfrom .core import Client\n",
            "lib/core.py": "class Client: ...\n",
            "app/__init__.py": "",
            "app/main.py": "from lib import core\n",
        },
    )
    assert "SC004" not in _codes(tmp_path)


def test_sc004_ignores_dunder_imports(tmp_path: Path):
    _write(
        tmp_path,
        {
            "lib/__init__.py": "__all__ = ['Client']\nfrom .core import Client\n__version__ = '1'\n",
            "lib/core.py": "class Client: ...\n",
            "app/__init__.py": "",
            "app/main.py": "from lib import __version__\n",
        },
    )
    assert "SC004" not in _codes(tmp_path)


def test_sc004_is_silent_without_any_door(tmp_path: Path):
    _write(
        tmp_path,
        {
            "lib/__init__.py": "",
            "lib/core.py": "def plumbing(): ...\n",
            "app/__init__.py": "",
            "app/main.py": "from lib.core import plumbing\n",
        },
    )
    assert "SC004" not in _codes(tmp_path)


def test_sc004_honours_a_door_declared_by_redundant_alias(tmp_path: Path):
    _write(
        tmp_path,
        {
            "lib/__init__.py": "from .core import Client as Client\n",
            "lib/core.py": "class Client: ...\ndef plumbing(): ...\n",
            "app/__init__.py": "",
            "app/main.py": "from lib.core import plumbing\n",
        },
    )
    diagnostics = [d for d in check_project(tmp_path) if d.code == "SC004"]
    assert [d.symbol for d in diagnostics] == ["plumbing"]


# ---------------------------------------------------------------------------
# SC005 — a door that contradicts itself
# ---------------------------------------------------------------------------


def test_sc005_flags_a_published_name_that_does_not_exist(tmp_path: Path):
    _write(
        tmp_path,
        {
            "lib/__init__.py": "from .core import Client\n__all__ = ['Client', 'Ghost']\n",
            "lib/core.py": "class Client: ...\n",
        },
    )
    diagnostics = [d for d in check_project(tmp_path) if d.code == "SC005"]
    assert [d.symbol for d in diagnostics] == ["Ghost"]


def test_sc005_flags_a_published_name_declared_internal(tmp_path: Path):
    _write(
        tmp_path,
        {
            "lib/__init__.py": "from .core import helper\n__all__ = ['helper']\n",
            "lib/core.py": "from scopify import internal\n\n@internal\ndef helper(): ...\n",
        },
    )
    diagnostics = [d for d in check_project(tmp_path) if d.code == "SC005"]
    assert len(diagnostics) == 1
    assert "@internal" in diagnostics[0].message


def test_sc005_ignores_undeclared_visibility_under_strict_default(tmp_path: Path):
    """``default_visibility = "internal"`` must not turn every export into a
    contradiction: only a *written* @internal disagrees with the door."""
    from scopify.config import ScopifyConfig
    from scopify.markers import Visibility

    _write(
        tmp_path,
        {
            "lib/__init__.py": "from .core import helper\n__all__ = ['helper']\n",
            "lib/core.py": "def helper(): ...\n",
        },
    )
    config = ScopifyConfig(default_visibility=Visibility.INTERNAL)
    assert [d.code for d in check_project(tmp_path, config=config) if d.code == "SC005"] == []


def test_sc005_accepts_a_submodule_as_a_published_name(tmp_path: Path):
    _write(
        tmp_path,
        {
            "lib/__init__.py": "__all__ = ['core']\n",
            "lib/core.py": "class Client: ...\n",
        },
    )
    assert "SC005" not in _codes(tmp_path)


def test_sc005_stays_quiet_when_a_star_import_hides_the_origin(tmp_path: Path):
    _write(
        tmp_path,
        {
            "lib/__init__.py": "from .core import *\n__all__ = ['Client']\n",
            "lib/core.py": "class Client: ...\n",
        },
    )
    assert "SC005" not in _codes(tmp_path)
