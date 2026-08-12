"""SC003 — mismatch between an explicit visibility annotation and Python's
leading-underscore naming convention.

Long before ``@public``/``@internal``/``@private`` existed, Python
developers already signalled "not part of the public API" with a single
leading underscore. When both signals are present and disagree, it is
usually an oversight rather than a deliberate choice:

* ``@public`` (or ``Annotated[T, Public]``) on an underscore-prefixed name —
  the name says "hidden", the decorator says "public". Flagged as an error:
  this is the contradiction most likely to leak something unintentionally.
* ``@internal`` (or ``Annotated[T, Internal]``) on a name with *no* leading
  underscore — the decorator is the actual source of truth here, so this is
  only a warning nudging towards a consistent style, not a hard error.

Only bare, unaliased references are recognised (``@public``, ``@internal``,
``Public``, ``Internal``) — dotted or aliased forms (``@scopify.internal``,
``from scopify import internal as hidden``) are left alone, both to keep
the check simple and so the anchor position used for the LSP "flip
visibility" quick fix is always an unambiguous, single-token span.
"""
from __future__ import annotations

import ast
from pathlib import Path

from scopify.diagnostics import Diagnostic

CODE = "SC003"

_PUBLIC_NAMES = {"public", "Public"}
_INTERNAL_NAMES = {"internal", "Internal"}


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def _has_leading_underscore(name: str) -> bool:
    return name.startswith("_") and not _is_dunder(name)


def _plain_visibility_ref(node: ast.expr) -> str | None:
    """The bare identifier text if ``node`` is a plain ``public``/``internal``/
    ``Public``/``Internal`` name reference; ``None`` for anything else
    (dotted, aliased, calls, or unrelated expressions)."""
    if isinstance(node, ast.Name) and (node.id in _PUBLIC_NAMES or node.id in _INTERNAL_NAMES):
        return node.id
    return None


def _annotated_visibility_ref(annotation: ast.expr | None) -> ast.Name | None:
    """The ``Public``/``Internal`` metadata node inside ``Annotated[T, ...]``, if any."""
    if not isinstance(annotation, ast.Subscript):
        return None
    tail = annotation.value
    tail_name = tail.attr if isinstance(tail, ast.Attribute) else getattr(tail, "id", "")
    if tail_name != "Annotated":
        return None
    sl = annotation.slice
    elts = sl.elts if isinstance(sl, ast.Tuple) else [sl]
    for meta in elts[1:]:
        if _plain_visibility_ref(meta) is not None:
            return meta
    return None


def check(source: str, module: str, file: Path) -> list[Diagnostic]:  # noqa: ARG001
    """Scan a single file's source for public/internal-vs-underscore mismatches.

    ``module`` is accepted for symmetry with the other single-file rules but
    unused here; every check in this rule is local to the file's own AST.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    diagnostics: list[Diagnostic] = []

    def emit(name: str, anchor: ast.Name) -> None:
        underscored = _has_leading_underscore(name)
        is_public = anchor.id in _PUBLIC_NAMES
        if is_public and underscored:
            diagnostics.append(
                Diagnostic(
                    code=CODE,
                    message=(
                        f"'{name}' is marked @public but its leading underscore "
                        "conventionally signals non-public API — this looks "
                        "like a naming/visibility mismatch."
                    ),
                    file=file,
                    line=anchor.lineno,
                    column=anchor.col_offset,
                    symbol=anchor.id,
                )
            )
        elif not is_public and not underscored:
            diagnostics.append(
                Diagnostic(
                    code=CODE,
                    message=(
                        f"'{name}' is marked @internal but has no leading "
                        "underscore, so it reads like public API — consider "
                        "prefixing it with '_' or confirming the restriction "
                        "is intentional."
                    ),
                    file=file,
                    line=anchor.lineno,
                    column=anchor.col_offset,
                    severity="warning",
                    symbol=anchor.id,
                )
            )

    def check_decorators(name: str, decorator_list: list[ast.expr]) -> None:
        for dec in decorator_list:
            ref = _plain_visibility_ref(dec)
            if ref is not None:
                emit(name, dec)
                return  # only the first visibility decorator is meaningful

    def visit_class(cls: ast.ClassDef) -> None:
        check_decorators(cls.name, cls.decorator_list)
        for child in cls.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                check_decorators(child.name, child.decorator_list)
            elif isinstance(child, ast.ClassDef):
                visit_class(child)
            elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                anchor = _annotated_visibility_ref(child.annotation)
                if anchor is not None:
                    emit(child.target.id, anchor)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            check_decorators(node.name, node.decorator_list)
        elif isinstance(node, ast.ClassDef):
            visit_class(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            anchor = _annotated_visibility_ref(node.annotation)
            if anchor is not None:
                emit(node.target.id, anchor)

    diagnostics.sort(key=lambda d: (d.line, d.column))
    return diagnostics
