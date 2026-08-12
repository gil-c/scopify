"""Discover Python source files within a project root."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

_SKIP_DIR_NAMES = {
    "__pycache__",
    "node_modules",
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "venv",
    ".venv",
    "env",
    ".env",
    "build",
    "dist",
}


def _should_skip(dir_name: str) -> bool:
    if dir_name in _SKIP_DIR_NAMES:
        return True
    # Skip dotfile directories.
    return dir_name.startswith(".") and dir_name not in {".",}


def discover_python_files(root: Path) -> Iterator[Path]:
    """Yield ``*.py`` files under ``root``, skipping junk directories."""
    root = Path(root)
    if root.is_file():
        if root.suffix == ".py":
            yield root
        return

    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (PermissionError, FileNotFoundError):
            continue
        for entry in entries:
            if entry.is_dir():
                if _should_skip(entry.name):
                    continue
                stack.append(entry)
            elif entry.is_file() and entry.suffix == ".py":
                yield entry

