"""SC001 once zones are declared: ``@internal`` means "my zone".

Every test below builds a real project on disk and runs the engine on it, so
what is asserted is the tool's actual answer, not a unit of plumbing.
"""
from pathlib import Path

import pytest

from scopify.engine import check_project

PYPROJECT = """
[tool.scopify.zones.core]
modules = ["pkg.core", "pkg.core.**"]
{core_extra}

[tool.scopify.zones.http]
modules = ["pkg.http", "pkg.http.**"]

[tool.scopify.zones.cli]
modules = ["pkg", "pkg.cli", "pkg.cli.**"]
"""

UTIL = """
from scopify import internal

@internal
def _only_core(): ...

@internal(to=["http"])
def _for_http(): ...

@internal(to="*")
def _for_all(): ...
"""


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _project(root: Path, *, core_extra: str = "") -> None:
    _write(root, "pyproject.toml", PYPROJECT.format(core_extra=core_extra))
    for package in ("pkg", "pkg/core", "pkg/http", "pkg/cli"):
        _write(root, f"{package}/__init__.py", "")
    _write(root, "pkg/core/util.py", UTIL)
    borrow = "from pkg.core.util import _only_core, _for_http, _for_all\n"
    _write(root, "pkg/http/client.py", borrow)
    _write(root, "pkg/cli/main.py", borrow)


def _blocked(root: Path) -> set[tuple[str, str]]:
    """Every SC001 as ``(symbol, zone that was refused)``."""
    found = set()
    for diagnostic in check_project(root):
        if diagnostic.code != "SC001":
            continue
        symbol = diagnostic.message.split("'")[1]
        found.add((symbol, diagnostic.file.parent.name))
    return found


def test_zone_replaces_the_project_as_the_boundary(tmp_path: Path):
    _project(tmp_path)
    # `_for_http` reaches http but not cli; `_for_all` reaches everywhere.
    assert _blocked(tmp_path) == {
        ("_only_core", "http"),
        ("_only_core", "cli"),
        ("_for_http", "cli"),
    }


def test_message_names_every_zone_the_symbol_reaches(tmp_path: Path):
    _project(tmp_path)
    message = next(
        d.message
        for d in check_project(tmp_path)
        if d.code == "SC001" and "_for_http" in d.message
    )
    assert "zones 'core', 'http'" in message
    assert "zone 'cli' cannot use it" in message


@pytest.mark.parametrize(
    "escape",
    ['exposes = ["_only_core"]', 'shares = { _only_core = ["http", "cli"] }'],
)
def test_a_zone_can_hand_out_a_symbol_without_touching_the_code(
    tmp_path: Path, escape: str
):
    """``exposes`` publishes to all zones, ``shares`` to the ones named."""
    _project(tmp_path, core_extra=escape)
    assert ("_only_core", "http") not in _blocked(tmp_path)
    assert ("_only_core", "cli") not in _blocked(tmp_path)


def test_shares_accepts_a_bare_string(tmp_path: Path):
    _project(tmp_path, core_extra='shares = { _only_core = "http" }')
    blocked = _blocked(tmp_path)
    assert ("_only_core", "http") not in blocked
    assert ("_only_core", "cli") in blocked


def test_shares_star_reaches_the_whole_project(tmp_path: Path):
    _project(tmp_path, core_extra='shares = { _only_core = "*" }')
    assert _blocked(tmp_path) == {("_for_http", "cli")}


def test_without_zones_the_boundary_is_still_the_project(tmp_path: Path):
    """No ``[tool.scopify.zones]``: behaviour is unchanged, nothing tightens."""
    for package in ("pkg", "pkg/core", "pkg/http"):
        _write(tmp_path, f"{package}/__init__.py", "")
    _write(tmp_path, "pkg/core/util.py", UTIL)
    _write(tmp_path, "pkg/http/client.py", "from pkg.core.util import _only_core\n")

    assert _blocked(tmp_path) == set()


def test_internal_to_star_published_in_all_is_still_a_contradiction(tmp_path: Path):
    """SC005 is about the door, not the zone: widening does not publish."""
    _write(
        tmp_path,
        "pkg/__init__.py",
        'from pkg.util import shared\n__all__ = ["shared"]\n',
    )
    _write(
        tmp_path,
        "pkg/util.py",
        'from scopify import internal\n\n@internal(to="*")\ndef shared(): ...\n',
    )

    codes = [d.code for d in check_project(tmp_path)]
    assert "SC005" in codes
