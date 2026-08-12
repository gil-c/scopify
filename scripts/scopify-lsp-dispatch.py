"""Stable entry point for PyCharm/LSP4IJ's *global* Scopify language server definition.

LSP4IJ registers user-defined language servers at the IDE-application level, not
per project (confirmed: PyCharm stores the command line in
``%APPDATA%\\JetBrains\\<product>\\options\\UserDefinedLanguageServerSettings.xml``,
shared by every project window). That means the "Command" field can only ever
point at ONE path -- it cannot itself differ per worktree/project.

This script solves that by being the thing that path points at (configure once,
never touch it again). It contains no third-party dependencies (stdlib only) so
it can run with any Python 3 interpreter, and at every launch it:

1. Resolves the *current* project root -- preferring an explicit root passed
   as ``argv[1]`` (PyCharm's ``$ProjectFileDir$`` macro, see Configure below)
   since LSP4IJ's "Working directory" setting is not always honored
   consistently and ``os.getcwd()`` alone proved unreliable in practice. As a
   safety net we also walk a few parent directories in case the root is a
   subdirectory of the project (e.g. a nested source root).
2. Looks for that project's OWN dedicated venv (``venv/Scripts/scopify-lsp.exe``
   on Windows, ``venv/bin/scopify-lsp`` elsewhere) and, if found, execs it
   in-place (``os.execv``) so the *editable install living in that exact
   worktree* is what actually serves diagnostics -- always the right rule
   version for whichever worktree/project window PyCharm happens to be running,
   with zero manual reconfiguration when a new worktree is created.
3. Otherwise (no venv yet, or an unrelated repo that never opted into
   Scopify) exits immediately without starting any server and without
   creating anything. This script never builds a venv itself -- that is
   .githooks/post-checkout's job (core.hooksPath=.githooks, shared repo-wide),
   which already builds it the moment a new worktree is created, before
   anyone opens PyCharm. If a project has no venv yet, Scopify just stays
   silent there until the hook (or a manual `pip install -e .[dev,lsp]`) has
   run -- no diagnostics, no crash, no hidden background work from the IDE.

Combined with Scopify's own pyproject.toml opt-in check (``_project_opts_in``
in ``scopify.lsp``), unrelated repos that don't opt into Scopify never get
diagnostics and never even spawn a process for it.

Configure once in PyCharm's LSP4IJ language server settings (Settings ->
Languages & Frameworks -> Language Servers -> Scopify -> Command):

    py -3 D:\\Dev\\scopify\\scripts\\scopify-lsp-dispatch.py $ProjectFileDir$

Point it at the MAIN checkout's copy of this script (not a worktree's), since
the main checkout is never deleted, so the command line never needs updating
again -- not even when worktrees are created or removed. The trailing
``$ProjectFileDir$`` is a PyCharm macro expanded to whichever project window
is currently starting the server; it is required (see point 1 above).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_MAX_PARENT_HOPS = 4


def _venv_lsp_executable(project_root: Path) -> Path | None:
    if os.name == "nt":
        candidate = project_root / "venv" / "Scripts" / "scopify-lsp.exe"
    else:
        candidate = project_root / "venv" / "bin" / "scopify-lsp"
    return candidate if candidate.is_file() else None


def _find_project_lsp_executable(explicit_root: str | None) -> Path | None:
    # Prefer an explicit project root (passed as argv[1], typically PyCharm's
    # $ProjectFileDir$ macro) over os.getcwd(): LSP4IJ's "Working directory"
    # setting is not always honored consistently, so cwd alone is not
    # reliable enough to locate the right worktree's venv.
    root = Path(explicit_root) if explicit_root else Path.cwd()
    for _ in range(_MAX_PARENT_HOPS + 1):
        found = _venv_lsp_executable(root)
        if found is not None:
            return found
        if (root / "pyproject.toml").is_file() or (root / ".git").exists():
            # Reached the project boundary; no per-project venv here, stop
            # looking further up rather than accidentally picking up an
            # unrelated ancestor project's venv.
            return None
        parent = root.parent
        if parent == root:
            return None
        root = parent
    return None


def main() -> int:
    # argv[1], when present, is the project root (PyCharm's $ProjectFileDir$
    # macro, configured as an extra "argument" alongside the interpreter and
    # this script). It is consumed here, not forwarded to the child process.
    explicit_root = sys.argv[1] if len(sys.argv) > 1 else None
    executable = _find_project_lsp_executable(explicit_root)
    if executable is None:
        # No venv for this project (not built yet, or an unrelated repo that
        # never opted in): exit quietly, no server, no diagnostics.
        return 0

    os.execv(str(executable), [str(executable)])
    return 0  # pragma: no cover - execv does not return on success


if __name__ == "__main__":
    sys.exit(main())
