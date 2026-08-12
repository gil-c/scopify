"""PA01x — detection of dynamic Python constructs that defeat static analysis.

Unlike SC001/SC002 (which need the whole-project import graph), these checks
are purely local to a single file: each source is parsed once and walked for
a fixed list of "escape the type/analysis system" patterns.

Every diagnostic can be silenced through one of three escape hatches:

* An inline trailing comment on the offending line: ``# scopify: allow-dynamic``
* A ``@dynamic`` (or ``@dynamic(reason="...")``) decorator on the enclosing
  function or class — silences every dynamic diagnostic raised anywhere in
  that function/class body.
* A module-level marker comment near the top of the file:
  ``# scopify: dynamic-module`` — silences every dynamic diagnostic in the
  whole module.
"""
from __future__ import annotations

import ast
from pathlib import Path

from scopify.diagnostics import Diagnostic

SC010 = "SC010"  # getattr/setattr/hasattr/delattr with a non-literal name
SC011 = "SC011"  # eval / exec / compile
SC012 = "SC012"  # importlib.import_module / __import__ with a non-literal target
SC013 = "SC013"  # module-level __getattr__ / __getattribute__
SC014 = "SC014"  # explicit custom metaclass
SC015 = "SC015"  # direct __dict__ mutation
SC016 = "SC016"  # frame introspection (inspect.currentframe/stack, sys._getframe)
SC017 = "SC017"  # monkey-patching an attribute of an imported name
SC018 = "SC018"  # globals()/locals()/vars() used for a write, not a read

_ATTR_BUILTINS = {"getattr", "setattr", "hasattr", "delattr"}
_EXEC_BUILTINS = {"eval", "exec", "compile"}
_DICT_MUTATORS = {"update", "pop", "popitem", "setdefault", "clear", "__setitem__", "__delitem__"}
_NAMESPACE_BUILTINS = {"globals", "locals", "vars"}
_FRAME_INTROSPECTORS = {"inspect.currentframe", "inspect.stack", "inspect.trace", "sys._getframe"}
_INLINE_MARKER = "scopify: allow-dynamic"
_MODULE_MARKER = "scopify: dynamic-module"
_MODULE_MARKER_SCAN_LINES = 20


def _dotted_name(node: ast.expr) -> str:
    """Best-effort dotted name for a ``Call.func`` or decorator expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return _dotted_name(node.func)
    return ""


def _collect_dynamic_aliases(tree: ast.AST) -> set[str]:
    """Names bound to ``scopify.dynamic`` in this module (handles aliasing)."""
    aliases = {"dynamic"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("scopify"):
            for alias in node.names:
                if alias.name == "dynamic":
                    aliases.add(alias.asname or "dynamic")
    return aliases


def _is_dynamic_decorator(dec: ast.expr, aliases: set[str]) -> bool:
    name = _dotted_name(dec)
    if not name:
        return False
    head = name.split(".", 1)[0]
    tail = name.rsplit(".", 1)[-1]
    return head in aliases or tail == "dynamic"


def _module_marker_present(source: str) -> bool:
    return any(_MODULE_MARKER in line for line in source.splitlines()[:_MODULE_MARKER_SCAN_LINES])


def _inline_allowed_lines(source: str) -> set[int]:
    return {i for i, line in enumerate(source.splitlines(), start=1) if _INLINE_MARKER in line}


def _dynamic_decorated_ranges(tree: ast.AST, aliases: set[str]) -> list[tuple[int, int]]:
    """(start_line, end_line) spans covered by an enclosing ``@dynamic``."""
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        is_defish = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        if is_defish and any(_is_dynamic_decorator(dec, aliases) for dec in node.decorator_list):
            start = min((dec.lineno for dec in node.decorator_list), default=node.lineno)
            end = getattr(node, "end_lineno", None) or node.lineno
            ranges.append((start, end))
    return ranges


def _is_literal_str(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _positional_or_keyword(call: ast.Call, index: int, keyword: str) -> ast.expr | None:
    if index < len(call.args):
        return call.args[index]
    for kw in call.keywords:
        if kw.arg == keyword:
            return kw.value
    return None


def _is_dunder_dict(node: ast.expr) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "__dict__"


def _namespace_builtin_call(node: ast.expr) -> str | None:
    """Return ``"globals"``/``"locals"``/``"vars"`` if ``node`` calls that builtin."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _NAMESPACE_BUILTINS
    ):
        return node.func.id
    return None


def _leftmost_name(node: ast.expr) -> str | None:
    """Walk down an attribute/subscript chain to the base ``Name``, if any."""
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _collect_imported_names(tree: ast.AST) -> set[str]:
    """Top-level names bound by ``import``/``from ... import`` in this file."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
    return names


def _collect_module_aliases(tree: ast.AST) -> dict[str, str]:
    """``import X [as Y]`` -> ``{local_name: "X"}`` (dotted names kept whole)."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".", 1)[0]] = alias.name
    return aliases


def _collect_from_aliases(tree: ast.AST) -> dict[str, tuple[str, str]]:
    """``from X import Y [as Z]`` -> ``{local_name: ("X", "Y")}``."""
    aliases: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if alias.name != "*":
                    aliases[alias.asname or alias.name] = (node.module, alias.name)
    return aliases


def _assignment_targets(node: ast.Assign | ast.AugAssign) -> list[ast.expr]:
    return node.targets if isinstance(node, ast.Assign) else [node.target]


def _span_text(lines: list[str], node: ast.AST) -> str | None:
    """Exact source text covered by ``node``, if it fits on a single line.

    Used to widen an LSP diagnostic's underline to the full offending
    expression (e.g. ``obj.__dict__.update``) instead of a single character.
    Returns ``None`` for multi-line spans, where the caller falls back to the
    default single-character underline (``Diagnostic`` only carries one
    line number, so a cross-line range can't be represented anyway).
    """
    end_lineno = getattr(node, "end_lineno", None)
    end_col = getattr(node, "end_col_offset", None)
    lineno = getattr(node, "lineno", None)
    col = getattr(node, "col_offset", None)
    if None in (end_lineno, end_col, lineno, col) or end_lineno != lineno:
        return None
    if not (0 <= lineno - 1 < len(lines)):
        return None
    return lines[lineno - 1][col:end_col]


def _name_column(lines: list[str], lineno: int, name: str, after: int) -> int:
    """Column of ``name`` on ``lineno`` at/after ``after`` (e.g. past ``def ``).

    Falls back to ``after`` if not found, so a diagnostic is never lost over a
    cosmetic underline-width detail.
    """
    if not (0 <= lineno - 1 < len(lines)):
        return after
    idx = lines[lineno - 1].find(name, after)
    return idx if idx != -1 else after


def _leaf_symbol_and_column(lines: list[str], attr_node: ast.Attribute) -> tuple[str, int]:
    """Column of an ``Attribute`` node's final segment, for underlining just the
    offending name rather than the whole dotted chain.

    E.g. for ``inspect.currentframe`` this returns ``("currentframe", <col of
    'c'>)`` -- the harmless ``inspect`` module prefix is left unmarked, since it
    is not itself the reason the diagnostic fires.
    """
    text = _span_text(lines, attr_node)
    if text is not None:
        idx = text.rfind(attr_node.attr)
        if idx != -1:
            return attr_node.attr, attr_node.col_offset + idx
    return attr_node.attr, attr_node.col_offset


def check(source: str, module: str, file: Path) -> list[Diagnostic]:  # noqa: ARG001
    """Scan a single file's source for dynamic constructs.

    ``module`` is accepted for symmetry with the other rules but unused here:
    every check in this rule is local to the file's own AST.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    if _module_marker_present(source):
        return []

    aliases = _collect_dynamic_aliases(tree)
    allowed_lines = _inline_allowed_lines(source)
    dynamic_ranges = _dynamic_decorated_ranges(tree, aliases)
    imported_names = _collect_imported_names(tree)
    module_aliases = _collect_module_aliases(tree)
    from_aliases = _collect_from_aliases(tree)
    source_lines = source.splitlines()

    def is_suppressed(lineno: int) -> bool:
        if lineno in allowed_lines:
            return True
        return any(start <= lineno <= end for start, end in dynamic_ranges)

    diagnostics: list[Diagnostic] = []

    def emit(
        code: str,
        message: str,
        node: ast.AST,
        *,
        severity: str = "error",
        symbol: str | None = None,
        column: int | None = None,
        span_node: ast.AST | None = None,
    ) -> None:
        """Record a diagnostic anchored at ``node`` (or ``column`` if given).

        ``symbol`` (or, if omitted, the source text spanned by ``span_node``)
        tells the LSP layer how wide to make the underline -- otherwise it
        would default to a single character, which is nearly invisible for
        anything but the shortest identifiers.
        """
        lineno = getattr(node, "lineno", 1)
        if is_suppressed(lineno):
            return
        if symbol is None and span_node is not None:
            symbol = _span_text(source_lines, span_node)
        diagnostics.append(
            Diagnostic(
                code=code,
                message=message,
                file=file,
                line=lineno,
                column=column if column is not None else getattr(node, "col_offset", 0),
                severity=severity,
                symbol=symbol,
            )
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = _dotted_name(node.func)
            simple_name = func_name.rsplit(".", 1)[-1]

            if simple_name in _ATTR_BUILTINS and isinstance(node.func, ast.Name):
                name_arg = _positional_or_keyword(node, 1, "name")
                if name_arg is not None and not _is_literal_str(name_arg):
                    emit(
                        SC010,
                        f"'{simple_name}()' is called with a non-literal attribute "
                        "name, which defeats static accessibility analysis.",
                        node,
                        symbol=simple_name,
                    )

            elif simple_name in _EXEC_BUILTINS and isinstance(node.func, ast.Name):
                emit(
                    SC011,
                    f"'{simple_name}()' executes dynamically generated code and "
                    "cannot be statically analysed.",
                    node,
                    symbol=simple_name,
                )

            elif func_name == "importlib.import_module" or (
                isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"
            ):
                target = _positional_or_keyword(node, 0, "name")
                if target is not None and not _is_literal_str(target):
                    leaf_symbol, leaf_col = _leaf_symbol_and_column(source_lines, node.func)
                    emit(
                        SC012,
                        "'importlib.import_module()' is called with a non-literal "
                        "module name and cannot be statically resolved.",
                        node,
                        symbol=leaf_symbol,
                        column=leaf_col,
                    )

            elif simple_name == "__import__" and isinstance(node.func, ast.Name):
                target = _positional_or_keyword(node, 0, "name")
                if target is not None and not _is_literal_str(target):
                    emit(
                        SC012,
                        "'__import__()' is called with a non-literal module name "
                        "and cannot be statically resolved.",
                        node,
                        symbol=simple_name,
                    )

            elif isinstance(node.func, ast.Attribute) and _is_dunder_dict(node.func.value):
                if node.func.attr in _DICT_MUTATORS:
                    emit(
                        SC015,
                        f"'.__dict__.{node.func.attr}()' mutates an object's "
                        "namespace directly, bypassing declared visibility.",
                        node,
                        span_node=node.func,
                    )

            elif isinstance(node.func, ast.Attribute) and node.func.attr in _DICT_MUTATORS:
                builtin_name = _namespace_builtin_call(node.func.value)
                if builtin_name is not None:
                    emit(
                        SC018,
                        f"'{builtin_name}().{node.func.attr}()' mutates the "
                        "namespace dict directly, bypassing declared visibility.",
                        node,
                        span_node=node.func,
                    )

            elif isinstance(node.func, ast.Attribute):
                base = _leftmost_name(node.func.value)
                real_module = module_aliases.get(base) if base else None
                if (real_module == "inspect" and node.func.attr in ("currentframe", "stack", "trace")) or (
                    real_module == "sys" and node.func.attr == "_getframe"
                ):
                    leaf_symbol, leaf_col = _leaf_symbol_and_column(source_lines, node.func)
                    emit(
                        SC016,
                        f"'{func_name}()' inspects call-stack frames, which "
                        "escapes static analysis.",
                        node,
                        symbol=leaf_symbol,
                        column=leaf_col,
                    )

            elif isinstance(node.func, ast.Name):
                mapped = from_aliases.get(node.func.id)
                if mapped in {
                    ("inspect", "currentframe"),
                    ("inspect", "stack"),
                    ("inspect", "trace"),
                    ("sys", "_getframe"),
                }:
                    emit(
                        SC016,
                        f"'{node.func.id}()' inspects call-stack frames, which "
                        "escapes static analysis.",
                        node,
                        symbol=node.func.id,
                    )

        elif isinstance(node, ast.Module):
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name in (
                    "__getattr__",
                    "__getattribute__",
                ):
                    prefix_len = len("async def ") if isinstance(stmt, ast.AsyncFunctionDef) else len("def ")
                    name_col = _name_column(
                        source_lines, stmt.lineno, stmt.name, stmt.col_offset + prefix_len
                    )
                    emit(
                        SC013,
                        f"module-level '{stmt.name}' intercepts attribute access "
                        "and cannot be statically analysed.",
                        stmt,
                        symbol=stmt.name,
                        column=name_col,
                    )

        elif isinstance(node, ast.ClassDef):
            for kw in node.keywords:
                if kw.arg == "metaclass":
                    emit(
                        SC014,
                        f"class '{node.name}' declares an explicit metaclass, "
                        "which can rewrite the class body dynamically.",
                        kw if getattr(kw, "lineno", None) else node,
                        severity="warning",
                        symbol="metaclass",
                    )

        elif isinstance(node, (ast.Assign, ast.AugAssign)):
            for target in _assignment_targets(node):
                if isinstance(target, ast.Subscript) and _is_dunder_dict(target.value):
                    emit(
                        SC015,
                        "subscript assignment into '__dict__' mutates an "
                        "object's namespace directly, bypassing declared visibility.",
                        node,
                        column=target.col_offset,
                        span_node=target,
                    )
                elif isinstance(target, ast.Attribute) and target.attr == "__dict__":
                    emit(
                        SC015,
                        "direct reassignment of '__dict__' replaces an "
                        "object's whole namespace, bypassing declared visibility.",
                        node,
                        column=target.col_offset,
                        span_node=target,
                    )
                elif isinstance(target, ast.Subscript):
                    builtin_name = _namespace_builtin_call(target.value)
                    if builtin_name is not None:
                        emit(
                            SC018,
                            f"subscript assignment into '{builtin_name}()' mutates "
                            "the namespace dict directly, bypassing declared visibility.",
                            node,
                            column=target.col_offset,
                            span_node=target,
                        )
                elif isinstance(target, ast.Attribute):
                    base = _leftmost_name(target)
                    if base and base in imported_names and base not in ("self", "cls"):
                        leaf_symbol, leaf_col = _leaf_symbol_and_column(source_lines, target)
                        emit(
                            SC017,
                            f"assigning to '{base}.{target.attr}' monkey-patches "
                            f"an attribute of the imported name '{base}'.",
                            node,
                            symbol=leaf_symbol,
                            column=leaf_col,
                        )

        elif isinstance(node, ast.Delete):
            for target in node.targets:
                if isinstance(target, ast.Subscript):
                    builtin_name = _namespace_builtin_call(target.value)
                    if builtin_name is not None:
                        emit(
                            SC018,
                            f"'del {builtin_name}()[...]' mutates the namespace "
                            "dict directly, bypassing declared visibility.",
                            node,
                            column=target.col_offset,
                            span_node=target,
                        )

    diagnostics.sort(key=lambda d: (d.line, d.column, d.code))
    return diagnostics
