"""SC002 — cross-module import of a symbol marked ``@private``."""
from pathlib import Path

from scopify.engine import check_project


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def test_cross_module_import_of_private_is_flagged(tmp_path: Path):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import private\n@private\ndef secret():\n    pass\n",
    )
    _write(tmp_path, "alpha/user.py", "from alpha.core import secret\n")

    diagnostics = check_project(tmp_path)
    codes = [d.code for d in diagnostics]
    assert "SC002" in codes
    diag = next(d for d in diagnostics if d.code == "SC002")
    assert "secret" in diag.message
    assert "alpha.core" in diag.message
    assert diag.file.name == "user.py"


def test_same_module_use_of_private_is_allowed(tmp_path: Path):
    # A private symbol used in the same module is not an import at all, so
    # the engine has no import to flag. We assert no diagnostic appears.
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import private\n@private\ndef secret():\n    pass\nsecret()\n",
    )

    diagnostics = check_project(tmp_path)
    assert [d for d in diagnostics if d.code == "SC002"] == []


def test_cross_package_import_of_private_is_flagged_with_both_codes(tmp_path: Path):
    # A private symbol crossing a package boundary is *also* an internal violation
    # — but private is the stronger rule, so SC002 must fire. SC001 currently
    # requires the symbol to be @internal, so it should not fire here.
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import private\n@private\ndef secret():\n    pass\n",
    )
    _write(tmp_path, "beta/__init__.py", "")
    _write(tmp_path, "beta/user.py", "from alpha.core import secret\n")

    diagnostics = check_project(tmp_path)
    codes = {d.code for d in diagnostics}
    assert "SC002" in codes


def test_public_symbol_never_triggers_sc002(tmp_path: Path):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import public\n@public\ndef api():\n    pass\n",
    )
    _write(tmp_path, "alpha/user.py", "from alpha.core import api\n")

    diagnostics = check_project(tmp_path)
    assert [d for d in diagnostics if d.code == "SC002"] == []

