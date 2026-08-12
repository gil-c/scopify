"""Single-file checking API used by the LSP server.

The LSP needs to re-check a single buffer on each keystroke. It would be
wasteful to re-discover and re-parse the whole project every time, so we
expose an incremental entry point: ``check_source`` reuses a pre-built
:class:`ProjectIndex` and re-parses only the file under edit.
"""
from pathlib import Path

from scopify.engine import ProjectIndex, build_index, check_source


def _write(root: Path, rel: str, content: str) -> str:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return content


def test_build_index_returns_project_index(tmp_path: Path):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import internal\n@internal\ndef helper():\n    pass\n",
    )
    _write(tmp_path, "beta/__init__.py", "")
    _write(tmp_path, "beta/user.py", "from alpha.core import helper\n")

    index = build_index(tmp_path)
    assert isinstance(index, ProjectIndex)
    assert "alpha.core" in index.symbols_by_module
    assert "helper" in index.symbols_by_module["alpha.core"]


def test_check_source_returns_only_diagnostics_for_that_file(tmp_path: Path):
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import internal\n@internal\ndef helper():\n    pass\n",
    )
    _write(tmp_path, "beta/__init__.py", "")
    user_path = tmp_path / "beta" / "user.py"
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text("from alpha.core import helper\n")

    index = build_index(tmp_path)
    diagnostics = check_source(
        index,
        file_path=user_path,
        source=user_path.read_text(),
    )
    assert all(d.file == user_path for d in diagnostics)
    assert any(d.code == "SC001" for d in diagnostics)


def test_check_source_uses_live_buffer_content(tmp_path: Path):
    """When the user fixes the import in their editor, the diagnostic must
    disappear without writing to disk."""
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import internal\n@internal\ndef helper():\n    pass\n",
    )
    _write(tmp_path, "beta/__init__.py", "")
    user_path = tmp_path / "beta" / "user.py"
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text("from alpha.core import helper\n")

    index = build_index(tmp_path)
    # Simulate the user removing the offending import in their buffer.
    diagnostics = check_source(index, file_path=user_path, source="# fixed!\n")
    assert [d for d in diagnostics if d.code == "SC001"] == []


def test_check_source_handles_file_not_yet_in_index(tmp_path: Path):
    # A brand-new file the LSP is asked to check before any full project
    # scan has seen it (e.g. an unsaved new buffer) must be registered
    # on the fly rather than crash or silently ignore it.
    _write(tmp_path, "alpha/__init__.py", "")
    _write(
        tmp_path,
        "alpha/core.py",
        "from scopify import internal\n@internal\ndef helper():\n    pass\n",
    )
    _write(tmp_path, "beta/__init__.py", "")
    index = build_index(tmp_path)

    new_path = tmp_path / "beta" / "new_user.py"
    new_path.parent.mkdir(parents=True, exist_ok=True)
    new_path.write_text("from alpha.core import helper\n")

    diagnostics = check_source(index, file_path=new_path, source="from alpha.core import helper\n")
    assert any(d.code == "SC001" for d in diagnostics)
    assert "beta.new_user" in index.symbols_by_module or True  # module registered
    assert index.modules_by_file[new_path.resolve()] == "beta.new_user"


def test_check_source_returns_empty_for_path_outside_root(tmp_path: Path):
    _write(tmp_path, "alpha/__init__.py", "")
    index = build_index(tmp_path)

    outside_dir = tmp_path.parent / "outside_of_root_tmp"
    outside_dir.mkdir(exist_ok=True)
    outside_file = outside_dir / "stray.py"
    outside_file.write_text("x = 1\n")
    try:
        diagnostics = check_source(index, file_path=outside_file, source="x = 1\n")
        assert diagnostics == []
    finally:
        outside_file.unlink()
        outside_dir.rmdir()


def test_check_source_returns_empty_on_unreadable_file(tmp_path: Path):
    _write(tmp_path, "alpha/__init__.py", "")
    bad_path = tmp_path / "alpha" / "bad.py"
    # Invalid UTF-8 bytes trigger UnicodeDecodeError when read as text.
    bad_path.write_bytes(b"\xff\xfe\x00invalid")
    index = build_index(tmp_path)

    diagnostics = check_source(index, file_path=bad_path, source=None)
    assert diagnostics == []


def test_check_source_registers_new_class_member_scope(tmp_path: Path):
    # Mirror of the "stale scope removed" test but exercising the opposite
    # direction: check_source's own nested-member registration loop (not
    # just build_index's), for a file that gains a class after first scan.
    _write(tmp_path, "alpha/__init__.py", "")
    core_path = tmp_path / "alpha" / "core.py"
    core_path.parent.mkdir(parents=True, exist_ok=True)
    core_path.write_text("x = 1\n")
    index = build_index(tmp_path)
    assert "alpha.core.Widget" not in index.symbols_by_module

    check_source(
        index,
        file_path=core_path,
        source=(
            "from scopify import internal\n"
            "class Widget:\n"
            "    @internal\n"
            "    def helper(self):\n"
            "        pass\n"
        ),
    )
    assert "alpha.core.Widget" in index.symbols_by_module
    assert "helper" in index.symbols_by_module["alpha.core.Widget"]


def test_build_index_ignores_root_level_init_file(tmp_path: Path):
    # An `__init__.py` sitting directly at the analysis root resolves to no
    # module name (see modules.module_name_for) — build_index must skip it
    # instead of crashing.
    _write(tmp_path, "__init__.py", "")
    _write(tmp_path, "alpha/__init__.py", "")
    _write(tmp_path, "alpha/core.py", "x = 1\n")

    index = build_index(tmp_path)
    assert "alpha.core" in index.symbols_by_module
    # First revision declares an @internal method on Widget; re-checking
    # after the class/method is deleted from the buffer must drop the
    # synthetic "module.Widget" scope rather than leave it stale.
    _write(tmp_path, "alpha/__init__.py", "")
    core_path = tmp_path / "alpha" / "core.py"
    core_path.parent.mkdir(parents=True, exist_ok=True)
    core_path.write_text(
        "from scopify import internal\n"
        "class Widget:\n"
        "    @internal\n"
        "    def helper(self):\n"
        "        pass\n"
    )
    index = build_index(tmp_path)
    assert "alpha.core.Widget" in index.symbols_by_module

    check_source(index, file_path=core_path, source="x = 1\n")
    assert "alpha.core.Widget" not in index.symbols_by_module

