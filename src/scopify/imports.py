"""Extract import statements from a Python source."""
from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class ImportRef:
    importer: str            # dotted name of the importing module
    from_module: str         # dotted name of the source module
    imported_name: str | None  # imported symbol, or None for `import X`
    alias: str | None
    lineno: int
    col_offset: int
    # True when the statement sits under ``if TYPE_CHECKING:``. Such an import
    # does not exist at run time: it only binds a name for annotations. Keeping
    # it in the dependency graph invents cycles the interpreter never sees —
    # httpx has 96 module cycles when they are counted and 1 when they are not.
    type_checking: bool = False
    # True when the statement sits at module level. An import written inside a
    # function is usually a cycle someone has already worked around by hand.
    top_level: bool = True


def _resolve_relative(
    level: int, base_module: str, target: str | None, *, is_package: bool = False
) -> str | None:
    """Resolve a `from .X import Y` style import to an absolute module name.

    ``is_package`` must be true when ``base_module`` is a package (its source
    is an ``__init__.py``). Python anchors relative imports on the *containing
    package*, which for a package's own ``__init__.py`` is the package itself:
    ``from .core import x`` inside ``lib/__init__.py`` means ``lib.core``,
    whereas the same line inside ``lib/mod.py`` also means ``lib.core`` only
    because one segment is dropped for the module itself.
    """
    if level == 0:
        return target
    parts = base_module.split(".")
    if is_package:
        # The package is its own anchor, so the first dot consumes nothing.
        parts = parts + [""]
    if level > len(parts):
        return None
    base_parts = parts[: len(parts) - level]
    if target:
        base_parts = base_parts + [target]
    if not base_parts:
        return None
    return ".".join(base_parts)


def is_type_checking_test(node: ast.expr) -> bool:
    """Recognise ``TYPE_CHECKING`` and ``typing.TYPE_CHECKING`` guards."""
    if isinstance(node, ast.Name):
        return node.id == "TYPE_CHECKING"
    if isinstance(node, ast.Attribute):
        return node.attr == "TYPE_CHECKING"
    return False


def _walk_imports(
    body: list[ast.stmt], *, type_checking: bool, top_level: bool
) -> Iterator[tuple[ast.stmt, bool, bool]]:
    """Yield ``(statement, type_checking, top_level)`` for every import found.

    A plain :func:`ast.walk` cannot answer either question: both depend on the
    blocks a statement is nested in, and that context is lost once the tree is
    flattened.
    """
    for stmt in body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            yield stmt, type_checking, top_level
        elif isinstance(stmt, ast.If):
            guarded = type_checking or is_type_checking_test(stmt.test)
            yield from _walk_imports(
                stmt.body, type_checking=guarded, top_level=top_level
            )
            yield from _walk_imports(
                stmt.orelse, type_checking=type_checking, top_level=top_level
            )
        elif isinstance(
            stmt,
            (ast.Try, ast.With, ast.AsyncWith, ast.For, ast.AsyncFor, ast.While),
        ):
            bodies: list[list[ast.stmt]] = [stmt.body]
            if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While, ast.Try)):
                bodies.append(stmt.orelse)
            if isinstance(stmt, ast.Try):
                bodies.append(stmt.finalbody)
                bodies.extend(handler.body for handler in stmt.handlers)
            for body in bodies:
                yield from _walk_imports(
                    body, type_checking=type_checking, top_level=top_level
                )
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield from _walk_imports(
                stmt.body, type_checking=type_checking, top_level=False
            )


def collect_imports(
    source: str, module: str, *, is_package: bool = False
) -> list[ImportRef]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    refs: list[ImportRef] = []
    for node, type_checking, top_level in _walk_imports(
        tree.body, type_checking=False, top_level=True
    ):
        if isinstance(node, ast.Import):
            for alias in node.names:
                refs.append(
                    ImportRef(
                        importer=module,
                        from_module=alias.name,
                        imported_name=None,
                        alias=alias.asname,
                        lineno=node.lineno,
                        col_offset=node.col_offset,
                        type_checking=type_checking,
                        top_level=top_level,
                    )
                )
            continue

        assert isinstance(node, ast.ImportFrom)
        resolved = _resolve_relative(
            node.level or 0, module, node.module, is_package=is_package
        )
        if resolved is None:
            continue
        for alias in node.names:
            if alias.name == "*":
                refs.append(
                    ImportRef(
                        importer=module,
                        from_module=resolved,
                        imported_name="*",
                        alias=None,
                        lineno=node.lineno,
                        col_offset=node.col_offset,
                        type_checking=type_checking,
                        top_level=top_level,
                    )
                )
                continue
            refs.append(
                ImportRef(
                    importer=module,
                    from_module=resolved,
                    imported_name=alias.name,
                    alias=alias.asname,
                    # Prefer the alias's own location so editors underline the
                    # imported name rather than the leading ``from``.
                    lineno=getattr(alias, "lineno", node.lineno),
                    col_offset=getattr(alias, "col_offset", node.col_offset),
                    type_checking=type_checking,
                    top_level=top_level,
                )
            )
    return refs
