"""End-to-end test of the access rule via the engine."""
from pathlib import Path

from scopify.engine import check_project


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def test_cross_package_import_of_internal_is_flagged(tmp_path: Path):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import internal\n@internal\ndef helper():\n    pass\n",
    )
    _write(tmp_path, "beta/__init__.py", "")
    _write(tmp_path, "beta/user.py", "from alpha.core import helper\n")

    diagnostics = check_project(tmp_path)

    codes = [d.code for d in diagnostics]
    assert "SC001" in codes
    msg = next(d for d in diagnostics if d.code == "SC001")
    assert "helper" in msg.message
    assert "alpha.core" in msg.message
    assert msg.file.name == "user.py"
    assert msg.line >= 1


def test_same_package_import_of_internal_is_allowed(tmp_path: Path):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import internal\n@internal\ndef helper():\n    pass\n",
    )
    _write(tmp_path, "alpha/user.py", "from alpha.core import helper\n")

    diagnostics = check_project(tmp_path)
    assert [d for d in diagnostics if d.code == "SC001"] == []


def test_public_symbol_is_importable_cross_package(tmp_path: Path):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import public\n@public\ndef api():\n    pass\n",
    )
    _write(tmp_path, "beta/__init__.py", "")
    _write(tmp_path, "beta/user.py", "from alpha.core import api\n")

    diagnostics = check_project(tmp_path)
    assert [d for d in diagnostics if d.code == "SC001"] == []


def test_subpackage_is_considered_same_package_root(tmp_path: Path):
    # alpha.sub.* should be able to import alpha.core internals: same top-level package.
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import internal\n@internal\ndef helper():\n    pass\n",
    )
    _write(tmp_path, "alpha/sub/__init__.py", "")
    _write(tmp_path, "alpha/sub/user.py", "from alpha.core import helper\n")

    diagnostics = check_project(tmp_path)
    assert [d for d in diagnostics if d.code == "SC001"] == []


def test_unknown_external_symbol_is_ignored(tmp_path: Path):
    # Importing from a module outside the project must not crash or produce noise.
    _write(tmp_path, "alpha/__init__.py", "")
    _write(tmp_path, "alpha/user.py", "import os\nfrom collections import OrderedDict\n")

    diagnostics = check_project(tmp_path)
    assert diagnostics == []


# --- Phase 3: re-exports via __init__.py --------------------------------------


def test_internal_symbol_reexported_via_init_is_importable_cross_package(tmp_path: Path):
    _write(tmp_path, "alpha/__init__.py", "from alpha.core import helper\n")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import internal\n@internal\ndef helper():\n    pass\n",
    )
    _write(tmp_path, "beta/__init__.py", "")
    _write(tmp_path, "beta/user.py", "from alpha import helper\n")

    diagnostics = check_project(tmp_path)
    assert [d for d in diagnostics if d.code == "SC001"] == []


def test_direct_import_bypassing_reexport_is_still_flagged(tmp_path: Path):
    # The re-export promotes `alpha.helper`, not the original `alpha.core.helper`.
    _write(tmp_path, "alpha/__init__.py", "from alpha.core import helper\n")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import internal\n@internal\ndef helper():\n    pass\n",
    )
    _write(tmp_path, "beta/__init__.py", "")
    _write(tmp_path, "beta/user.py", "from alpha.core import helper\n")

    diagnostics = check_project(tmp_path)
    assert "SC001" in [d.code for d in diagnostics]


def test_private_symbol_cannot_be_reexported(tmp_path: Path):
    # The __init__.py's own import of a @private symbol from another module
    # is itself a SC002 violation — re-exporting it must not be possible.
    _write(tmp_path, "alpha/__init__.py", "from alpha.core import _secret\n")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import private\n@private\ndef _secret():\n    pass\n",
    )

    diagnostics = check_project(tmp_path)
    assert "SC002" in [d.code for d in diagnostics]


# --- Phase 3: configurable default_visibility policy --------------------------


def test_undecorated_symbol_is_public_by_default(tmp_path: Path):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(tmp_path, "alpha/core.py", "def helper():\n    pass\n")
    _write(tmp_path, "beta/__init__.py", "")
    _write(tmp_path, "beta/user.py", "from alpha.core import helper\n")

    diagnostics = check_project(tmp_path)
    assert [d for d in diagnostics if d.code == "SC001"] == []


def test_undecorated_symbol_is_internal_with_strict_default_policy(tmp_path: Path):
    _write(tmp_path, "scopify.toml", 'default_visibility = "internal"\n')
    _write(tmp_path, "alpha/__init__.py", "")
    _write(tmp_path, "alpha/core.py", "def helper():\n    pass\n")
    _write(tmp_path, "beta/__init__.py", "")
    _write(tmp_path, "beta/user.py", "from alpha.core import helper\n")

    diagnostics = check_project(tmp_path)
    assert "SC001" in [d.code for d in diagnostics]


def test_explicit_public_decorator_overrides_strict_default_policy(tmp_path: Path):
    _write(tmp_path, "scopify.toml", 'default_visibility = "internal"\n')
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import public\n@public\ndef helper():\n    pass\n",
    )
    _write(tmp_path, "beta/__init__.py", "")
    _write(tmp_path, "beta/user.py", "from alpha.core import helper\n")

    diagnostics = check_project(tmp_path)
    assert [d for d in diagnostics if d.code == "SC001"] == []


# --- Phase 3: Annotated[T, Marker] attributes -----------------------------------


def test_annotated_internal_attribute_cross_package_import_is_flagged(tmp_path: Path):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from typing import Annotated\n"
        "from scopify import Internal\n"
        "CONFIG: Annotated[dict, Internal] = {}\n",
    )
    _write(tmp_path, "beta/__init__.py", "")
    _write(tmp_path, "beta/user.py", "from alpha.core import CONFIG\n")

    diagnostics = check_project(tmp_path)
    codes = [d.code for d in diagnostics]
    assert "SC001" in codes


def test_annotated_private_attribute_cross_module_import_is_flagged(tmp_path: Path):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from typing import Annotated\n"
        "from scopify import Private\n"
        "_secret: Annotated[str, Private] = ''\n",
    )
    _write(tmp_path, "alpha/user.py", "from alpha.core import _secret\n")

    diagnostics = check_project(tmp_path)
    assert "SC002" in [d.code for d in diagnostics]


def test_annotated_public_attribute_is_importable_cross_package(tmp_path: Path):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from typing import Annotated\n"
        "from scopify import Public\n"
        "API_VERSION: Annotated[str, Public] = '1.0'\n",
    )
    _write(tmp_path, "beta/__init__.py", "")
    _write(tmp_path, "beta/user.py", "from alpha.core import API_VERSION\n")

    diagnostics = check_project(tmp_path)
    assert [d for d in diagnostics if d.code == "SC001"] == []



