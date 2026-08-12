"""Discovery: walk a project root and return its Python files."""
from pathlib import Path

from scopify.discovery import discover_python_files


def test_discovers_py_files_recursively(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n")
    (tmp_path / "pkg" / "sub").mkdir()
    (tmp_path / "pkg" / "sub" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "sub" / "b.py").write_text("y = 2\n")
    (tmp_path / "README.md").write_text("nope")

    files = {p.relative_to(tmp_path).as_posix() for p in discover_python_files(tmp_path)}

    assert files == {
        "pkg/__init__.py",
        "pkg/a.py",
        "pkg/sub/__init__.py",
        "pkg/sub/b.py",
    }


def test_skips_hidden_and_venv_dirs(tmp_path: Path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "junk.py").write_text("")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.py").write_text("")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "y.py").write_text("")
    (tmp_path / "keep.py").write_text("")

    files = {p.name for p in discover_python_files(tmp_path)}
    assert files == {"keep.py"}

