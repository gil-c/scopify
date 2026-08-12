"""Attribute-access usage sites, beyond plain ``from X import Y`` statements.

``imports.collect_imports`` only sees the ``from``/``import`` statement
itself. Two common access patterns bypass it entirely and were previously
invisible to SC001/SC002:

* Qualified module access: ``import pkg.sub`` then ``pkg.sub.attr``.
* Class member access: ``SomeClass.member`` / ``instance.member``, where
  ``instance`` was assigned directly from a call to a known class reference.

Both are normalised into :class:`~scopify.imports.ImportRef` so the
existing SC001/SC002 rules consume them unchanged. Class members are looked
up via a synthetic ``"module.ClassName"`` scope key (see
``engine._index_symbols``).

This is a heuristic, not a type checker: it resolves simple local-name
bindings (``import``/``from import``/``var = Call(...)``) in source order
regardless of control flow, and gives up silently on anything more dynamic
(the ``@dynamic`` escape hatch remains the answer for those cases).
"""
from __future__ import annotations

import ast
from collections.abc import Iterable

from scopify.imports import ImportRef, _resolve_relative


def _flatten_attribute(node: ast.expr) -> list[str] | None:
    """Turn ``a.b.c`` into ``["a", "b", "c"]``; ``None`` if not a plain chain."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    parts.reverse()
    return parts


def _resolve(chain: list[str], name_to_scope: dict[str, str]) -> list[str] | None:
    """Rewrite ``chain`` through ``name_to_scope`` into a fully dotted path."""
    if not chain or chain[0] not in name_to_scope:
        return None
    return name_to_scope[chain[0]].split(".") + chain[1:]


def collect_usages(source: str, module: str, known_scopes: Iterable[str]) -> list[ImportRef]:
    """Return synthetic usage sites for attribute access chains in ``source``."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    known = set(known_scopes)
    name_to_scope: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                name_to_scope[alias.asname or root] = alias.name if alias.asname else root
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_relative(node.level or 0, module, node.module)
            if resolved is None:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                name_to_scope[alias.asname or alias.name] = f"{resolved}.{alias.name}"

    # Second pass: track `var = KnownRef(...)` so `var.member` resolves like
    # `KnownRef.member` (e.g. an instance of an imported class).
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
            continue
        chain = _flatten_attribute(node.value.func)
        if chain is None:
            continue
        resolved = _resolve(chain, name_to_scope)
        if resolved is None:
            continue
        full = ".".join(resolved)
        for target in node.targets:
            if isinstance(target, ast.Name):
                name_to_scope[target.id] = full

    usages: list[ImportRef] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        chain = _flatten_attribute(node)
        if chain is None or len(chain) < 2:
            continue
        resolved = _resolve(chain, name_to_scope)
        if resolved is None or len(resolved) < 2:
            continue
        scope, attr = ".".join(resolved[:-1]), resolved[-1]
        if scope not in known:
            continue
        usages.append(
            ImportRef(
                importer=module,
                from_module=scope,
                imported_name=attr,
                alias=None,
                lineno=node.lineno,
                col_offset=node.col_offset,
            )
        )
    return usages
