"""Language Server Protocol server for Scopify.

Lets any LSP-aware editor (PyCharm via LSP4IJ, VS Code, Neovim, Helix…) get
live underlining as the user edits Python files.

The server keeps one :class:`ProjectIndex` per workspace root and refreshes it
incrementally on file open / save / change events.

Two extra behaviours make it practical to run one Scopify checkout per
worktree, each hacking on the rules independently, all inside the same IDE
installation at once:

* **Per-project opt-in** (:func:`_project_opts_in`): a project is only
  linted if it declares ``scopify`` as a dependency or ships a
  ``scopify.toml`` / ``[tool.scopify]`` section. Editors like PyCharm
  register a language server IDE-wide, not per project, so without this an
  unrelated repo opened in the same IDE window would get Scopify
  diagnostics too.
* **Hot-reloading rules** (:class:`RuleWatcher`): Scopify is normally
  installed editable (``pip install -e .``), so editing a rule already
  changes what the *next* CLI run sees. The LSP server, however, is one
  long-lived process — this watcher polls its own source files and
  reloads+re-lints automatically on change, so there is no server restart
  and no manual step between editing a rule and seeing updated squiggles.

Run it via::

    scopify-lsp                # stdio transport (what most clients want)

Requires the optional ``pygls`` dependency::

    pip install 'scopify[lsp]'
"""
from __future__ import annotations

import contextlib
import importlib
import logging
import os
import re
import sys
import threading
from pathlib import Path
from urllib.parse import unquote, urlparse

try:  # pragma: no cover - optional dependency
    from lsprotocol import types as lsp
    try:
        # pygls >= 2.0
        from pygls.lsp.server import LanguageServer
    except ImportError:
        # pygls 1.x
        from pygls.server import LanguageServer
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "scopify-lsp requires the 'pygls' extra. Install with: pip install 'scopify[lsp]'"
    ) from exc

from scopify import __version__
from scopify import engine as engine_mod
from scopify.diagnostics import Diagnostic as PADiagnostic
from scopify.engine import ProjectIndex  # noqa: F401 - re-exported for type hints only

SERVER_NAME = "scopify-lsp"

# Rule/engine modules that are safe to hot-reload in-process. Deliberately
# excludes ``scopify.lsp`` (the module driving the currently-running server)
# and ``scopify.cli``: reloading the code that is on the call stack right
# now is unsafe, and neither module is a "rule" a user would iterate on.
_RELOAD_BLOCKLIST = {"scopify.lsp", "scopify.cli", "scopify"}

# Reload leaves before the modules that import them, so that by the time
# ``scopify.engine`` is reloaded it re-imports already-fresh rule modules.
_RELOAD_ORDER_HINT = (
    "scopify.markers",
    "scopify.diagnostics",
    "scopify.discovery",
    "scopify.modules",
    "scopify.imports",
    "scopify.symbols",
    "scopify.graph",
    "scopify.reexports",
    "scopify.config",
    "scopify.suppression",
    "scopify.rules",
    "scopify.rules.access",
    "scopify.rules.private",
    "scopify.rules.dynamic",
    "scopify.rules.naming",
    "scopify.engine",
)


def _uri_to_path(uri: str) -> Path:
    """Convert a ``file://`` URI into a :class:`Path`."""
    parsed = urlparse(uri)
    path = unquote(parsed.path)
    # On Windows a URI looks like ``file:///D:/foo`` -> path is ``/D:/foo``.
    if path.startswith("/") and len(path) >= 3 and path[2] == ":":
        path = path[1:]
    return Path(path)


def _to_lsp_diagnostic(d: PADiagnostic) -> lsp.Diagnostic:
    severity = (
        lsp.DiagnosticSeverity.Error
        if d.severity == "error"
        else lsp.DiagnosticSeverity.Warning
    )
    # Scopify emits 1-based lines and 0-based columns; LSP wants both 0-based.
    line = max(d.line - 1, 0)
    col = max(d.column, 0)
    # When the rule knows the offending symbol's name, widen the range to its
    # full length so editors underline the whole identifier instead of a
    # nearly-invisible single character.
    width = len(d.symbol) if getattr(d, "symbol", None) else 1
    return lsp.Diagnostic(
        range=lsp.Range(
            start=lsp.Position(line=line, character=col),
            end=lsp.Position(line=line, character=col + width),
        ),
        message=d.message,
        severity=severity,
        code=d.code,
        source="scopify",
    )


# Case-preserving flip used by the SC003 "switch visibility" quick fix --
# keeps ``Public``/``Internal`` (the ``Annotated[T, ...]`` metadata spelling)
# distinct from the lowercase decorator spelling.
_FLIP = {"public": "internal", "internal": "public", "Public": "Internal", "Internal": "Public"}


def _suppress_code_action(uri: str, d: PADiagnostic, lines: list[str]) -> lsp.CodeAction | None:
    """A quick fix that appends/extends a ``# scopify: ignore[CODE]`` comment.

    Returns ``None`` when the line already carries a directive that already
    silences this diagnostic's code (nothing useful to offer).
    """
    from scopify.suppression import parse_ignore_directive

    idx = max(d.line - 1, 0)
    line_text = lines[idx] if 0 <= idx < len(lines) else ""
    existing = parse_ignore_directive(line_text)
    if existing is not None and (not existing or d.code in existing):
        return None  # already suppressed (bare ignore, or this code listed)

    if existing is not None:
        codes = sorted(existing | {d.code})
        match = re.search(r"#\s*scopify:\s*ignore(?:\[[A-Za-z0-9,\s]*\])?", line_text)
        start, end = match.span()
        new_text = f"# scopify: ignore[{','.join(codes)}]"
    else:
        start = end = len(line_text)
        new_text = f"  # scopify: ignore[{d.code}]"

    edit = lsp.TextEdit(
        range=lsp.Range(
            start=lsp.Position(line=idx, character=start),
            end=lsp.Position(line=idx, character=end),
        ),
        new_text=new_text,
    )
    return lsp.CodeAction(
        title=f"scopify: ignore {d.code} on this line",
        kind=lsp.CodeActionKind.QuickFix,
        diagnostics=[_to_lsp_diagnostic(d)],
        edit=lsp.WorkspaceEdit(changes={uri: [edit]}),
    )


def _visibility_flip_actions(uri: str, d: PADiagnostic, lines: list[str]) -> list[lsp.CodeAction]:
    """SC003-only quick fix: flip ``@public``/``Public`` <-> ``@internal``/``Internal``.

    Anchored at ``d.column..d.column + len(d.symbol)`` (see ``rules.naming``),
    with a safety check that the buffer still contains the expected text at
    that exact span -- guards against a stale diagnostic being applied to a
    buffer that has since drifted (e.g. another edit landed first).
    """
    if d.code != "SC003" or not d.symbol or d.symbol not in _FLIP:
        return []
    idx = max(d.line - 1, 0)
    line_text = lines[idx] if 0 <= idx < len(lines) else ""
    start, end = d.column, d.column + len(d.symbol)
    if line_text[start:end] != d.symbol:
        return []
    replacement = _FLIP[d.symbol]
    edit = lsp.TextEdit(
        range=lsp.Range(
            start=lsp.Position(line=idx, character=start),
            end=lsp.Position(line=idx, character=end),
        ),
        new_text=replacement,
    )
    label = replacement if replacement[0].isupper() else f"@{replacement}"
    return [
        lsp.CodeAction(
            title=f"scopify: change to {label}",
            kind=lsp.CodeActionKind.QuickFix,
            diagnostics=[_to_lsp_diagnostic(d)],
            edit=lsp.WorkspaceEdit(changes={uri: [edit]}),
        )
    ]


def code_actions_for_document(
    uri: str, diagnostics: list[PADiagnostic], source: str
) -> list[lsp.CodeAction]:
    """All quick fixes applicable to ``diagnostics`` reported on ``source``.

    Pure and server-independent so it can be unit-tested directly (see
    ``tests/test_lsp.py``) without spinning up a real ``CodeActionParams``.
    """
    lines = source.splitlines()
    actions: list[lsp.CodeAction] = []
    for d in diagnostics:
        suppress = _suppress_code_action(uri, d, lines)
        if suppress is not None:
            actions.append(suppress)
        actions.extend(_visibility_flip_actions(uri, d, lines))
    return actions


def _project_opts_in(root: Path) -> bool:
    """Return whether ``root`` actually wants Scopify to run on it.

    The LSP client (e.g. PyCharm/LSP4IJ) typically registers ``scopify-lsp``
    for every ``*.py`` file in the IDE, regardless of which project window is
    focused -- LSP4IJ's server registrations are IDE-wide, not per-project
    (see the project README for details). To avoid linting unrelated repos
    that happen to be open in the same editor, a project must *opt in* by
    either declaring ``scopify`` as a dependency in its ``pyproject.toml``
    or by shipping a ``scopify.toml`` / ``[tool.scopify]`` section. A repo
    with neither gets zero diagnostics, silently and automatically -- no
    per-project IDE configuration required.
    """
    if (root / "scopify.toml").is_file():
        return True
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return False
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        import tomllib  # Python >= 3.11
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]
    try:
        data = tomllib.loads(text)
    except Exception:  # pragma: no cover - malformed pyproject.toml
        return False
    if "scopify" in data.get("tool", {}):
        return True
    project = data.get("project", {})
    deps = list(project.get("dependencies", ()))
    for extra_deps in project.get("optional-dependencies", {}).values():
        deps.extend(extra_deps)
    return any(
        dep.split(";", 1)[0].strip().split(">")[0].split("=")[0].split("<")[0].strip().lower()
        == "scopify"
        for dep in deps
    )


def _watched_scopify_source_files() -> dict[str, Path]:
    """Map every currently-loaded, hot-reloadable ``scopify.*`` module to
    its backing ``.py`` file, for mtime-based change detection.
    """
    files: dict[str, Path] = {}
    for name, module in list(sys.modules.items()):
        if not name.startswith("scopify.") and name != "scopify":
            continue
        if name in _RELOAD_BLOCKLIST:
            continue
        path = getattr(module, "__file__", None)
        if path:
            files[name] = Path(path)
    return files


class RuleWatcher:
    """Hot-reloads Scopify's own rule/engine code when it changes on disk.

    Because ``scopify-lsp`` is installed editable (``pip install -e .``),
    editing a file under ``src/scopify/rules/`` already changes what the
    *next* run of the CLI sees for free. The LSP server, however, is a
    long-lived process that imported those modules once at startup -- Python
    does not re-execute module code just because the file on disk changed.

    This watcher polls the mtimes of Scopify's own source files on a
    background thread and, on any change, calls :func:`importlib.reload` on
    the affected modules (leaves first, ``scopify.engine`` last) and then
    asks the server to drop its cached project indexes and re-lint every
    open document. The net effect: editing a rule and saving is reflected in
    PyCharm's live squiggles within ``interval`` seconds, with no server
    restart and no manual action.
    """

    def __init__(self, server: ScopifyLanguageServer, interval: float = 1.0) -> None:
        self._server = server
        self._interval = interval
        self._mtimes: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot()

    def _snapshot(self) -> None:
        for name, path in _watched_scopify_source_files().items():
            with contextlib.suppress(OSError):
                self._mtimes[name] = path.stat().st_mtime

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="scopify-rule-watcher", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:  # pragma: no cover - timing-dependent
        logger = logging.getLogger("scopify")
        while not self._stop.wait(self._interval):
            try:
                changed = self._changed_modules()
                if changed:
                    self._reload(changed)
            except Exception:
                # A single bad iteration (e.g. the LSP client hasn't
                # finished initializing yet, or a reload/relint edge case)
                # must never kill this daemon thread -- otherwise every
                # future edit would silently stop hot-reloading until the
                # whole server process is restarted, defeating the point.
                logger.exception("scopify: rule watcher iteration failed")

    def _changed_modules(self) -> list[str]:
        changed = []
        for name, path in _watched_scopify_source_files().items():
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if self._mtimes.get(name) != mtime:
                self._mtimes[name] = mtime
                changed.append(name)
        return changed

    def _reload(self, changed: list[str]) -> None:
        logger = logging.getLogger("scopify")
        ordered = [n for n in _RELOAD_ORDER_HINT if n in sys.modules]
        extra = [
            n
            for n in sys.modules
            if (n.startswith("scopify.") or n == "scopify")
            and n not in _RELOAD_BLOCKLIST
            and n not in ordered
        ]
        for name in [*extra, *ordered]:
            try:
                importlib.reload(sys.modules[name])
            except Exception:
                logger.exception("scopify: hot-reload of %s failed", name)
                return
        logger.info("scopify: hot-reloaded %s", ", ".join(sorted(changed)))
        self._server.rebuild_and_relint()


class ScopifyLanguageServer(LanguageServer):
    """One :class:`ProjectIndex` per *project root* — not per LSP workspace.

    A single LSP workspace (e.g. the cloned ``scopify`` repo) may contain
    several independent Python projects (each demo under ``demos/`` has its
    own ``pyproject.toml``). We pick the *nearest enclosing* project root
    for every file so that module names resolve correctly.
    """

    def __init__(self) -> None:
        super().__init__(SERVER_NAME, __version__)
        self.indexes: dict[Path, ProjectIndex] = {}
        self._opt_in_cache: dict[Path, bool] = {}
        self.rule_watcher: RuleWatcher | None = None

    def index_for_file(self, file_path: Path) -> ProjectIndex | None:
        """Return (and cache) the index for the project that owns ``file_path``.

        Returns ``None`` if the owning project hasn't opted in to Scopify
        (see :func:`_project_opts_in`) -- e.g. an unrelated repo that just
        happens to be open in the same IDE instance.
        """
        root = _guess_root(file_path.resolve())
        opted_in = self._opt_in_cache.get(root)
        if opted_in is None:
            opted_in = _project_opts_in(root)
            self._opt_in_cache[root] = opted_in
        if not opted_in:
            return None
        index = self.indexes.get(root)
        if index is None:
            # Always call through the module so a hot-reloaded
            # ``scopify.engine`` (see RuleWatcher) is picked up immediately,
            # even though this method itself was never reloaded.
            index = engine_mod.build_index(root)
            self.indexes[root] = index
        return index

    def refresh_file(self, uri: str, source: str | None) -> None:
        path = _uri_to_path(uri).resolve()
        index = self.index_for_file(path)
        if index is None:
            self.publish(uri, [])
            return
        diagnostics = engine_mod.check_source(index, file_path=path, source=source)
        self.publish(uri, [_to_lsp_diagnostic(d) for d in diagnostics])

    def rebuild_and_relint(self) -> None:
        """Drop every cached project index and re-check all open documents.

        Called by :class:`RuleWatcher` right after a hot-reload so that a
        change to a rule's implementation is reflected in already-open
        editors automatically, without the user re-opening files or
        restarting the server.
        """
        self.indexes.clear()
        self._opt_in_cache.clear()
        try:
            documents = list(self.workspace.text_documents.items())
        except RuntimeError:
            # The LSP client hasn't finished the initialize handshake yet
            # (e.g. a rule file was edited moments after the server
            # process started). There are no open documents to re-lint
            # yet -- the cleared caches above are enough to make the very
            # first refresh_file() call use the fresh code.
            return
        for uri, doc in documents:
            self.refresh_file(uri, doc.source)

    def publish(self, uri: str, diagnostics: list) -> None:
        """Send ``textDocument/publishDiagnostics`` for ``uri``.

        Wrapping the pygls call in a tiny indirection makes the server easy to
        monkeypatch in tests and shields us from minor API drift between
        pygls 1.x and 2.x.
        """
        params = lsp.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics)
        if hasattr(self, "text_document_publish_diagnostics"):
            self.text_document_publish_diagnostics(params)
        else:  # pragma: no cover - pygls 1.x fallback
            self.publish_diagnostics(uri, diagnostics)


def _guess_root(path: Path) -> Path:
    """Walk up from ``path`` to find the nearest project root.

    A project root is the closest ancestor directory that contains a
    ``pyproject.toml`` or ``scopify.toml``. Falls back to the file's parent
    directory when none is found.
    """
    candidates = [path, *path.parents] if path.is_dir() else list(path.parents)
    for parent in candidates:
        if (parent / "pyproject.toml").exists() or (parent / "scopify.toml").exists():
            return parent
    return path.parent


def create_server(*, watch_rules: bool = True) -> ScopifyLanguageServer:
    server = ScopifyLanguageServer()

    if watch_rules and not os.environ.get("SCOPIFY_LSP_NO_WATCH"):
        # Hot-reload Scopify's own rules on change -- see RuleWatcher's
        # docstring. Disable with SCOPIFY_LSP_NO_WATCH=1 (e.g. for a
        # packaged/non-editable install where the source never changes).
        server.rule_watcher = RuleWatcher(server)
        server.rule_watcher.start()

    @server.feature(lsp.INITIALIZED)
    def _on_initialized(ls: ScopifyLanguageServer, params) -> None:  # pragma: no cover  # noqa: ARG001
        # No eager indexing: a single workspace can contain several
        # independent Python projects (e.g. the demos folder). Indexes are
        # built lazily per file, rooted at the nearest enclosing
        # ``pyproject.toml`` / ``scopify.toml``.
        logging.getLogger("scopify").info(
            "initialized with %d workspace folder(s)",
            len(getattr(ls.workspace, "folders", {}) or {}),
        )

    @server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
    def _on_open(ls: ScopifyLanguageServer, params: lsp.DidOpenTextDocumentParams) -> None:
        ls.refresh_file(params.text_document.uri, params.text_document.text)

    @server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
    def _on_change(ls: ScopifyLanguageServer, params: lsp.DidChangeTextDocumentParams) -> None:
        doc = ls.workspace.get_text_document(params.text_document.uri)
        ls.refresh_file(params.text_document.uri, doc.source)

    @server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
    def _on_save(ls: ScopifyLanguageServer, params: lsp.DidSaveTextDocumentParams) -> None:
        doc = ls.workspace.get_text_document(params.text_document.uri)
        ls.refresh_file(params.text_document.uri, doc.source)

    @server.feature(
        lsp.TEXT_DOCUMENT_CODE_ACTION,
        lsp.CodeActionOptions(code_action_kinds=[lsp.CodeActionKind.QuickFix]),
    )
    def _on_code_action(
        ls: ScopifyLanguageServer, params: lsp.CodeActionParams
    ) -> list[lsp.CodeAction]:
        uri = params.text_document.uri
        path = _uri_to_path(uri).resolve()
        index = ls.index_for_file(path)
        if index is None:
            return []
        doc = ls.workspace.get_text_document(uri)
        diagnostics = engine_mod.check_source(index, file_path=path, source=doc.source)
        lo, hi = params.range.start.line, params.range.end.line
        in_range = [d for d in diagnostics if lo <= max(d.line - 1, 0) <= hi]
        return code_actions_for_document(uri, in_range, doc.source)

    return server


def main() -> None:  # pragma: no cover - entrypoint
    log_path = os.environ.get("SCOPIFY_LSP_LOG")
    if log_path:
        logging.basicConfig(
            filename=log_path,
            level=logging.DEBUG,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        logging.getLogger("scopify").info("scopify-lsp starting (pid=%s)", os.getpid())
    create_server().start_io()


if __name__ == "__main__":  # pragma: no cover
    main()







