"""Smoke tests for the LSP server."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("pygls")
pytest.importorskip("lsprotocol")
from scopify import engine as engine_mod  # noqa: E402
from scopify.diagnostics import Diagnostic as PADiagnostic  # noqa: E402
from scopify.lsp import (  # noqa: E402
    _guess_root,
    _project_opts_in,
    _to_lsp_diagnostic,
    _uri_to_path,
    create_server,
)


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
def test_uri_to_path_windows_drive(tmp_path: Path):
    uri = tmp_path.as_uri()
    assert _uri_to_path(uri).resolve() == tmp_path.resolve()
def test_diagnostic_conversion_uses_zero_based_line(tmp_path: Path):
    pad = PADiagnostic(code="SC001", message="boom", file=tmp_path / "x.py",
                       line=5, column=2, severity="error")
    lsp_diag = _to_lsp_diagnostic(pad)
    assert lsp_diag.range.start.line == 4
    assert lsp_diag.range.start.character == 2
    assert lsp_diag.code == "SC001"
    assert lsp_diag.source == "scopify"
def test_diagnostic_range_widens_to_symbol_name(tmp_path: Path):
    pad = PADiagnostic(code="SC001", message="boom", file=tmp_path / "x.py",
                       line=1, column=10, severity="error", symbol="helper")
    lsp_diag = _to_lsp_diagnostic(pad)
    assert lsp_diag.range.start.character == 10
    assert lsp_diag.range.end.character == 10 + len("helper")
def test_diagnostic_range_falls_back_to_one_char_when_no_symbol(tmp_path: Path):
    pad = PADiagnostic(code="SC001", message="boom", file=tmp_path / "x.py",
                       line=1, column=0)
    assert _to_lsp_diagnostic(pad).range.end.character == 1
def test_guess_root_prefers_pyproject(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    nested = tmp_path / "pkg" / "sub" / "mod.py"
    nested.parent.mkdir(parents=True)
    nested.write_text("x = 1\n")
    assert _guess_root(nested) == tmp_path
def test_guess_root_prefers_nearest_pyproject(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='repo'\n")
    inner = tmp_path / "demos" / "demo_a"
    inner.mkdir(parents=True)
    (inner / "pyproject.toml").write_text("[project]\nname='demo_a'\n")
    nested_file = inner / "pkg" / "mod.py"
    nested_file.parent.mkdir(parents=True)
    nested_file.write_text("x = 1\n")
    assert _guess_root(nested_file) == inner
def test_refresh_file_publishes_diagnostics_for_violation(tmp_path: Path, monkeypatch):
    _write(tmp_path, "pyproject.toml", "[project]\nname='demo'\ndependencies=['scopify']\n")
    _write(tmp_path, "alpha/__init__.py", "")
    _write(tmp_path, "alpha/core.py",
           "from scopify import internal\n@internal\ndef helper():\n    pass\n")
    _write(tmp_path, "beta/__init__.py", "")
    user = tmp_path / "beta" / "user.py"
    user.write_text("from alpha.core import helper\n")
    server = create_server(watch_rules=False)
    published = []
    monkeypatch.setattr(server, "publish",
                        lambda uri, diags: published.append((uri, diags)))
    server.refresh_file(user.as_uri(), source=user.read_text())
    assert len(published) == 1
    uri, diags = published[0]
    assert uri == user.as_uri()
    assert any(d.code == "SC001" for d in diags)
def test_refresh_file_clears_diagnostics_when_buffer_is_fixed(tmp_path: Path, monkeypatch):
    _write(tmp_path, "pyproject.toml", "[project]\nname='demo'\ndependencies=['scopify']\n")
    _write(tmp_path, "alpha/__init__.py", "")
    _write(tmp_path, "alpha/core.py",
           "from scopify import internal\n@internal\ndef helper():\n    pass\n")
    _write(tmp_path, "beta/__init__.py", "")
    user = tmp_path / "beta" / "user.py"
    user.write_text("from alpha.core import helper\n")
    server = create_server(watch_rules=False)
    published = []
    monkeypatch.setattr(server, "publish",
                        lambda uri, diags: published.append((uri, diags)))
    server.refresh_file(user.as_uri(), source="# fixed\n")
    assert published[-1][1] == []
def test_refresh_file_routes_each_demo_to_its_own_index(tmp_path: Path, monkeypatch):
    _write(tmp_path, "pyproject.toml", "[project]\nname='repo'\ndependencies=['scopify']\n")
    for demo in ("demo_a", "demo_b"):
        _write(tmp_path, f"demos/{demo}/pyproject.toml",
               f"[project]\nname='{demo}'\ndependencies=['scopify']\n")
        _write(tmp_path, f"demos/{demo}/alpha/__init__.py", "")
        _write(tmp_path, f"demos/{demo}/alpha/core.py",
               "from scopify import internal\n@internal\ndef helper():\n    pass\n")
        _write(tmp_path, f"demos/{demo}/beta/__init__.py", "")
        _write(tmp_path, f"demos/{demo}/beta/user.py",
               "from alpha.core import helper\n")
    server = create_server(watch_rules=False)
    published = []
    monkeypatch.setattr(server, "publish",
                        lambda uri, diags: published.append((uri, diags)))
    for demo in ("demo_a", "demo_b"):
        user = tmp_path / "demos" / demo / "beta" / "user.py"
        server.refresh_file(user.as_uri(), source=user.read_text())
    assert len(published) == 2
    for _uri, diags in published:
        assert any(d.code == "SC001" for d in diags)


# ---------------------------------------------------------------------------
# Per-project opt-in: an unrelated repo open in the same IDE gets no
# diagnostics, automatically, with no manual per-project IDE configuration.
# ---------------------------------------------------------------------------
def test_project_opts_in_via_pyproject_dependency(tmp_path: Path):
    _write(tmp_path, "pyproject.toml", "[project]\nname='x'\ndependencies=['scopify']\n")
    assert _project_opts_in(tmp_path) is True
def test_project_opts_in_via_optional_dependency(tmp_path: Path):
    _write(tmp_path, "pyproject.toml",
           "[project]\nname='x'\n[project.optional-dependencies]\nlsp=['scopify']\n")
    assert _project_opts_in(tmp_path) is True
def test_project_opts_in_via_tool_section(tmp_path: Path):
    _write(tmp_path, "pyproject.toml", "[project]\nname='x'\n[tool.scopify]\n")
    assert _project_opts_in(tmp_path) is True
def test_project_opts_in_via_standalone_scopify_toml(tmp_path: Path):
    _write(tmp_path, "pyproject.toml", "[project]\nname='x'\n")
    _write(tmp_path, "scopify.toml", "default_visibility = 'public'\n")
    assert _project_opts_in(tmp_path) is True
def test_project_does_not_opt_in_by_default(tmp_path: Path):
    _write(tmp_path, "pyproject.toml", "[project]\nname='some-other-repo'\ndependencies=['requests']\n")
    assert _project_opts_in(tmp_path) is False
def test_project_without_pyproject_does_not_opt_in(tmp_path: Path):
    assert _project_opts_in(tmp_path) is False
def test_refresh_file_stays_silent_for_a_repo_that_has_not_opted_in(tmp_path: Path, monkeypatch):
    # A completely unrelated Python repo -- no scopify dependency anywhere --
    # that just happens to be open in the same IDE/LSP client instance.
    _write(tmp_path, "pyproject.toml", "[project]\nname='unrelated'\ndependencies=['requests']\n")
    _write(tmp_path, "alpha/__init__.py", "")
    _write(tmp_path, "alpha/core.py",
           "from scopify import internal\n@internal\ndef helper():\n    pass\n")
    _write(tmp_path, "beta/__init__.py", "")
    user = tmp_path / "beta" / "user.py"
    user.write_text("from alpha.core import helper\n")
    server = create_server(watch_rules=False)
    published = []
    monkeypatch.setattr(server, "publish",
                        lambda uri, diags: published.append((uri, diags)))
    server.refresh_file(user.as_uri(), source=user.read_text())
    assert published == [(user.as_uri(), [])]


# ---------------------------------------------------------------------------
# Hot-reload: editing Scopify's own source is picked up automatically, with
# no server restart. Exercised against a throwaway fake module so the test
# never mutates the real, currently-running scopify package.
# ---------------------------------------------------------------------------
def test_rule_watcher_detects_mtime_change(tmp_path: Path, monkeypatch):
    import sys
    import types

    from scopify import lsp as lsp_module

    fake_file = tmp_path / "fake_rule.py"
    fake_file.write_text("VALUE = 1\n")
    fake_module = types.ModuleType("scopify.fake_rule_for_test")
    fake_module.__file__ = str(fake_file)
    monkeypatch.setitem(sys.modules, "scopify.fake_rule_for_test", fake_module)

    server = create_server(watch_rules=False)
    watcher = lsp_module.RuleWatcher(server, interval=999)
    assert watcher._changed_modules() == []  # nothing touched yet

    # Bump the mtime forward so the change is detected even on filesystems
    # with coarse (e.g. 2s, FAT-style) mtime resolution.
    new_mtime = fake_file.stat().st_mtime + 5
    fake_file.write_text("VALUE = 2\n")
    os.utime(fake_file, (new_mtime, new_mtime))
    assert watcher._changed_modules() == ["scopify.fake_rule_for_test"]
    assert watcher._changed_modules() == []  # second call: no further change
def test_rule_watcher_reload_orders_leaves_before_engine_and_relints(monkeypatch):
    from scopify import lsp as lsp_module

    server = create_server(watch_rules=False)
    relint_calls = []
    monkeypatch.setattr(server, "rebuild_and_relint", lambda: relint_calls.append(True))

    # Exercise the *orchestration* logic against real, already-loaded scopify
    # modules, but stub out importlib.reload itself so the test never
    # mutates the actual running scopify package (which other tests in this
    # same process still depend on).
    reload_order = []
    monkeypatch.setattr(
        lsp_module.importlib, "reload", lambda mod: reload_order.append(mod.__name__)
    )

    watcher = lsp_module.RuleWatcher(server, interval=999)  # never auto-fires
    watcher._reload(["scopify.rules.access"])

    assert "scopify.rules.access" in reload_order
    assert "scopify.engine" in reload_order
    # Leaves (rule modules) must be reloaded before scopify.engine, which
    # re-imports them -- otherwise engine would keep referencing stale code.
    assert reload_order.index("scopify.rules.access") < reload_order.index("scopify.engine")
    assert relint_calls == [True]
def test_rule_watcher_stops_and_skips_relint_when_a_reload_fails(monkeypatch):
    from scopify import lsp as lsp_module

    server = create_server(watch_rules=False)
    relint_calls = []
    monkeypatch.setattr(server, "rebuild_and_relint", lambda: relint_calls.append(True))

    def _boom(_mod):
        raise SyntaxError("broken rule file")

    monkeypatch.setattr(lsp_module.importlib, "reload", _boom)

    watcher = lsp_module.RuleWatcher(server, interval=999)
    watcher._reload(["scopify.rules.access"])  # must not raise

    assert relint_calls == []  # a broken edit must not blow away working diagnostics
def test_rule_watcher_ignores_blocklisted_modules(tmp_path: Path):
    from scopify.lsp import _RELOAD_BLOCKLIST, _watched_scopify_source_files

    assert "scopify.lsp" in _RELOAD_BLOCKLIST
    assert "scopify.lsp" not in _watched_scopify_source_files()


# ---------------------------------------------------------------------------
# Quick fixes: "suppress on this line" (any rule) and "flip visibility"
# (SC003 only). Exercised as pure functions against a fake ``uri`` and
# in-memory source text -- no real CodeActionParams/server transport needed.
# ---------------------------------------------------------------------------
from scopify.lsp import (  # noqa: E402
    _suppress_code_action,
    _visibility_flip_actions,
    code_actions_for_document,
)


def test_suppress_action_appends_new_ignore_comment(tmp_path: Path):
    pad = PADiagnostic(code="SC001", message="boom", file=tmp_path / "x.py",
                       line=1, column=0, symbol="helper")
    lines = ["from alpha.core import helper"]
    action = _suppress_code_action("file:///x.py", pad, lines)
    edit = action.edit.changes["file:///x.py"][0]
    assert edit.new_text == "  # scopify: ignore[SC001]"
    assert edit.range.start.character == len(lines[0])
def test_suppress_action_extends_existing_directive(tmp_path: Path):
    pad = PADiagnostic(code="SC003", message="boom", file=tmp_path / "x.py",
                       line=1, column=0, symbol="internal")
    lines = ["@internal  # scopify: ignore[SC001]"]
    action = _suppress_code_action("file:///x.py", pad, lines)
    edit = action.edit.changes["file:///x.py"][0]
    assert edit.new_text == "# scopify: ignore[SC001,SC003]"
def test_suppress_action_returns_none_when_code_already_ignored(tmp_path: Path):
    pad = PADiagnostic(code="SC001", message="boom", file=tmp_path / "x.py",
                       line=1, column=0, symbol="helper")
    lines = ["x  # scopify: ignore[SC001]"]
    assert _suppress_code_action("file:///x.py", pad, lines) is None
def test_suppress_action_returns_none_when_bare_ignore_present(tmp_path: Path):
    pad = PADiagnostic(code="SC002", message="boom", file=tmp_path / "x.py",
                       line=1, column=0, symbol="helper")
    lines = ["x  # scopify: ignore"]
    assert _suppress_code_action("file:///x.py", pad, lines) is None
def test_visibility_flip_action_public_to_internal(tmp_path: Path):
    pad = PADiagnostic(code="SC003", message="boom", file=tmp_path / "x.py",
                       line=1, column=1, symbol="public")
    lines = ["@public"]
    actions = _visibility_flip_actions("file:///x.py", pad, lines)
    assert len(actions) == 1
    assert actions[0].title == "scopify: change to @internal"
    edit = actions[0].edit.changes["file:///x.py"][0]
    assert edit.new_text == "internal"
    assert edit.range.start.character == 1
    assert edit.range.end.character == 1 + len("public")
def test_visibility_flip_action_annotated_metadata_preserves_case(tmp_path: Path):
    pad = PADiagnostic(code="SC003", message="boom", file=tmp_path / "x.py",
                       line=1, column=18, symbol="Internal")
    lines = ["x: Annotated[int, Internal]"]
    actions = _visibility_flip_actions("file:///x.py", pad, lines)
    assert actions[0].title == "scopify: change to Public"
def test_visibility_flip_action_skipped_for_non_sc003(tmp_path: Path):
    pad = PADiagnostic(code="SC001", message="boom", file=tmp_path / "x.py",
                       line=1, column=1, symbol="public")
    assert _visibility_flip_actions("file:///x.py", pad, ["@public"]) == []
def test_visibility_flip_action_guards_against_buffer_drift(tmp_path: Path):
    pad = PADiagnostic(code="SC003", message="boom", file=tmp_path / "x.py",
                       line=1, column=1, symbol="public")
    # The buffer has since changed underneath the stale diagnostic's column.
    lines = ["@something_else"]
    assert _visibility_flip_actions("file:///x.py", pad, lines) == []
def test_code_actions_for_document_combines_both_families(tmp_path: Path):
    pad = PADiagnostic(code="SC003", message="boom", file=tmp_path / "x.py",
                       line=1, column=1, symbol="public", severity="error")
    source = "@public\ndef _secret(): ...\n"
    actions = code_actions_for_document("file:///x.py", [pad], source)
    titles = {a.title for a in actions}
    assert "scopify: ignore SC003 on this line" in titles
    assert "scopify: change to @internal" in titles
def test_code_action_feature_is_registered(tmp_path: Path):
    server = create_server(watch_rules=False)
    assert "textDocument/codeAction" in server.protocol.fm.features
def test_code_action_end_to_end_offers_suppress_and_flip(tmp_path: Path):
    _write(tmp_path, "pyproject.toml", "[project]\nname='demo'\ndependencies=['scopify']\n")
    mod = tmp_path / "mod.py"
    mod.write_text("from scopify import public\n\n@public\ndef _secret():\n    pass\n")
    server = create_server(watch_rules=False)
    diagnostics = engine_mod.check_source(server.index_for_file(mod), file_path=mod, source=mod.read_text())
    assert any(d.code == "SC003" for d in diagnostics)
    actions = code_actions_for_document(mod.as_uri(), diagnostics, mod.read_text())
    assert any(a.title == "scopify: change to @internal" for a in actions)


