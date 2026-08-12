"""Baseline support for scopify check.

A baseline captures the set of violations that exist in a project *today*,
so that CI only fails on *new* violations introduced after the baseline was
recorded.  This is the standard "incremental adoption" pattern used by mypy,
ruff, and similar tools.

Workflow::

    # Record current state (one-time or after a bulk-fix session):
    scopify check src/ --write-baseline scopify-baseline.json

    # In CI: fail only if new violations appear:
    scopify check src/ --baseline scopify-baseline.json

Baseline format (v1)::

    {
      "version": 1,
      "entries": [
        {"file": "src/pkg/mod.py", "code": "SC001", "line": 12, "col": 0},
        ...
      ]
    }

File paths are stored relative to the project root so the baseline is
portable across machines and worktrees.

If line numbers shift (e.g. after a refactor), an entry no longer matches
and the corresponding violation will be reported as new.  Simply re-run
``--write-baseline`` after bulk-fixing or accepting the drift.
"""
from __future__ import annotations

import json
from pathlib import Path

from scopify.diagnostics import Diagnostic

_FORMAT_VERSION = 1


def _entry(diag: Diagnostic, root: Path) -> dict:
    try:
        rel = diag.file.relative_to(root)
    except ValueError:
        rel = diag.file  # fallback: absolute (shouldn't happen in normal use)
    return {
        "file": rel.as_posix(),
        "code": diag.code,
        "line": diag.line,
        "col": diag.column,
    }


def write_baseline(diagnostics: list[Diagnostic], root: Path, path: Path) -> None:
    """Serialise *diagnostics* as a baseline JSON file at *path*."""
    root = Path(root).resolve()
    payload = {
        "version": _FORMAT_VERSION,
        "entries": [_entry(d, root) for d in sorted(diagnostics, key=lambda d: (str(d.file), d.line, d.column, d.code))],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_baseline(path: Path) -> frozenset[tuple[str, str, int, int]]:
    """Return the set of ``(rel_file_posix, code, line, col)`` recorded in *path*.

    Raises :exc:`ValueError` for unrecognised format versions so callers can
    surface a clear error instead of silently ignoring stale baselines.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    version = data.get("version")
    if version != _FORMAT_VERSION:
        raise ValueError(
            f"scopify-baseline: unsupported format version {version!r} "
            f"(expected {_FORMAT_VERSION}). Re-generate with --write-baseline."
        )
    entries: set[tuple[str, str, int, int]] = set()
    for e in data.get("entries", []):
        entries.add((e["file"], e["code"], e["line"], e["col"]))
    return frozenset(entries)


def filter_new(
    diagnostics: list[Diagnostic],
    root: Path,
    baseline: frozenset[tuple[str, str, int, int]],
) -> list[Diagnostic]:
    """Return only diagnostics that are *not* present in *baseline*."""
    root = Path(root).resolve()
    result: list[Diagnostic] = []
    for d in diagnostics:
        try:
            rel = d.file.relative_to(root).as_posix()
        except ValueError:
            rel = str(d.file)
        if (rel, d.code, d.line, d.column) not in baseline:
            result.append(d)
    return result
