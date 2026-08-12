"""Unit tests for the generic inline ``# scopify: ignore`` suppression."""
from __future__ import annotations

from pathlib import Path

from scopify.diagnostics import Diagnostic
from scopify.suppression import (
    filter_suppressed,
    is_line_suppressed,
    parse_ignore_directive,
)


def test_parse_ignore_directive_absent_returns_none():
    assert parse_ignore_directive("x = 1") is None
def test_parse_ignore_directive_bare_returns_empty_set():
    assert parse_ignore_directive("x = 1  # scopify: ignore") == set()
def test_parse_ignore_directive_with_codes_normalizes_case_and_whitespace():
    directive = parse_ignore_directive("x = 1  # scopify: ignore[sc001, Sc003]")
    assert directive == {"SC001", "SC003"}
def test_parse_ignore_directive_empty_brackets_returns_empty_set():
    assert parse_ignore_directive("x = 1  # scopify: ignore[]") == set()
def test_is_line_suppressed_out_of_range_is_false():
    assert is_line_suppressed(["x = 1"], 5, "SC001") is False
    assert is_line_suppressed(["x = 1"], 0, "SC001") is False
def test_is_line_suppressed_bare_directive_covers_every_code():
    lines = ["x = 1  # scopify: ignore"]
    assert is_line_suppressed(lines, 1, "SC001") is True
    assert is_line_suppressed(lines, 1, "SC999") is True
def test_is_line_suppressed_scoped_directive_only_covers_listed_codes():
    lines = ["x = 1  # scopify: ignore[SC001]"]
    assert is_line_suppressed(lines, 1, "SC001") is True
    assert is_line_suppressed(lines, 1, "SC002") is False
def test_is_line_suppressed_no_directive_is_false():
    assert is_line_suppressed(["x = 1"], 1, "SC001") is False


def test_filter_suppressed_drops_matching_diagnostic(tmp_path: Path):
    file = tmp_path / "mod.py"
    diag = Diagnostic(code="SC001", message="boom", file=file, line=2, column=0)
    sources = {"pkg.mod": "a = 1\nb = 2  # scopify: ignore[SC001]\n"}
    modules_by_file = {file: "pkg.mod"}
    assert filter_suppressed([diag], sources, modules_by_file) == []
def test_filter_suppressed_keeps_diagnostic_for_unrelated_code(tmp_path: Path):
    file = tmp_path / "mod.py"
    diag = Diagnostic(code="SC002", message="boom", file=file, line=2, column=0)
    sources = {"pkg.mod": "a = 1\nb = 2  # scopify: ignore[SC001]\n"}
    modules_by_file = {file: "pkg.mod"}
    assert filter_suppressed([diag], sources, modules_by_file) == [diag]
def test_filter_suppressed_keeps_diagnostic_when_module_unknown(tmp_path: Path):
    file = tmp_path / "mod.py"
    diag = Diagnostic(code="SC001", message="boom", file=file, line=1, column=0)
    assert filter_suppressed([diag], {}, {}) == [diag]
def test_filter_suppressed_keeps_diagnostic_when_source_missing(tmp_path: Path):
    file = tmp_path / "mod.py"
    diag = Diagnostic(code="SC001", message="boom", file=file, line=1, column=0)
    modules_by_file = {file: "pkg.mod"}
    assert filter_suppressed([diag], {}, modules_by_file) == [diag]
