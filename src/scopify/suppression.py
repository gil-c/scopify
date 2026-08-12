"""Inline suppression: silence any Scopify diagnostic on a single line.

Unlike the dynamic-rule-specific escape hatches (``@dynamic``, the module-
level ``# scopify: dynamic-module`` marker), this is a *generic* mechanism
that works for every rule, including the cross-file SC001/SC002 checks that
previously had no way to be silenced locally at all:

    from alpha.core import helper  # scopify: ignore[SC001]

    @internal
    def _secret(): ...  # scopify: ignore[SC003]

A bare ``# scopify: ignore`` (no brackets) silences *every* diagnostic
reported on that line, regardless of code — use sparingly.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from scopify.diagnostics import Diagnostic

_IGNORE_RE = re.compile(r"#\s*scopify:\s*ignore(?:\[([A-Za-z0-9,\s]*)\])?")


def parse_ignore_directive(line: str) -> set[str] | None:
    """Return the set of codes suppressed on ``line``.

    ``None`` means no directive is present at all. An empty ``set`` means a
    bare ``# scopify: ignore`` — every code on that line is suppressed.
    """
    match = _IGNORE_RE.search(line)
    if match is None:
        return None
    codes = match.group(1)
    if not codes:
        return set()
    return {c.strip().upper() for c in codes.split(",") if c.strip()}


def is_line_suppressed(source_lines: list[str], lineno: int, code: str) -> bool:
    """Whether ``code`` is silenced by a directive on 1-based ``lineno``."""
    if not (1 <= lineno <= len(source_lines)):
        return False
    directive = parse_ignore_directive(source_lines[lineno - 1])
    if directive is None:
        return False
    return not directive or code.upper() in directive


def filter_suppressed(
    diagnostics: list[Diagnostic],
    sources_by_module: Mapping[str, str],
    modules_by_file: Mapping[Path, str],
) -> list[Diagnostic]:
    """Drop every diagnostic silenced by an inline ``# scopify: ignore`` comment."""
    kept: list[Diagnostic] = []
    lines_cache: dict[str, list[str]] = {}
    for d in diagnostics:
        module = modules_by_file.get(d.file)
        source = sources_by_module.get(module) if module is not None else None
        if source is None:
            kept.append(d)
            continue
        lines = lines_cache.setdefault(module, source.splitlines())
        if is_line_suppressed(lines, d.line, d.code):
            continue
        kept.append(d)
    return kept
