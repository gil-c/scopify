"""The published API surface — a package's ``__all__`` read as a *door*.

Python has no keyword for "public to my users" versus "public inside my
project", but it does have two long-standing conventions that encode exactly
that, in a package's ``__init__.py``:

* ``__all__ = [...]`` — the explicit list of published names;
* ``from .app import Flask as Flask`` — the deliberate redundant alias, which
  PEP 484 defines as an *explicit re-export* (it is what type checkers honour
  under ``--no-implicit-reexport``).

Scopify treats either one as a **door**: the names a package promises to the
outside world. Anything the package defines but does not publish is, at most,
``@internal`` — usable throughout the project, never promised to a consumer.

Both conventions are already universal (``httpx`` uses the first, ``flask``
the second), so this requires no annotation, no configuration and no
migration: a project's existing façade is enough for Scopify to tell an API
surface from project plumbing on the very first run.

This module only extracts the declaration. Enforcement lives in
``scopify.rules.api`` (SC004 / SC005).
"""
from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
from pathlib import Path

_ALL = "__all__"


def _string_items(node: ast.expr | None) -> list[str] | None:
    """Return the string literals of a list/tuple/set node, or ``None``.

    ``None`` means "not a literal sequence of strings" — a computed
    ``__all__`` that Scopify cannot resolve statically.
    """
    if not isinstance(node, ast.List | ast.Tuple | ast.Set):
        return None
    names: list[str] = []
    for element in node.elts:
        if isinstance(element, ast.Constant) and isinstance(element.value, str):
            names.append(element.value)
    return names


def collect_exports(source: str) -> frozenset[str] | None:
    """Return the names declared in ``__all__``, or ``None`` if there is none.

    An empty set is meaningful (``__all__ = []`` — a package that publishes
    nothing) and is therefore distinct from ``None`` (no declaration at all,
    i.e. no door: the package makes no promise either way).

    Handles the shapes seen in the wild:
    ``__all__ = [...]``, ``__all__ += [...]``, ``__all__ = __all__ + [...]``,
    ``__all__.extend([...])`` and ``__all__.append("x")``. Non-literal
    entries are skipped rather than failing the whole declaration.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    names: set[str] = set()
    declared = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if not any(isinstance(t, ast.Name) and t.id == _ALL for t in node.targets):
                continue
            declared = True
            value = node.value
            # `__all__ = __all__ + [...]` / `[...] + __all__`
            if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
                for side in (value.left, value.right):
                    names.update(_string_items(side) or [])
            else:
                names.update(_string_items(value) or [])
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name) and node.target.id == _ALL:
                declared = True
                names.update(_string_items(node.value) or [])
        elif isinstance(node, ast.Call):
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if not (isinstance(func.value, ast.Name) and func.value.id == _ALL):
                continue
            if func.attr == "extend" and node.args:
                declared = True
                names.update(_string_items(node.args[0]) or [])
            elif func.attr == "append" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    declared = True
                    names.add(arg.value)

    return frozenset(names) if declared else None


def collect_explicit_reexports(source: str) -> frozenset[str]:
    """Return names re-exported through the PEP 484 redundant-alias form.

    ``from .app import Flask as Flask`` and ``import json as json`` both state
    "this name is part of my public surface" — the marker type checkers use
    under ``--no-implicit-reexport``. A plain ``from .app import Flask``
    carries no such intent and is ignored.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return frozenset()

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.asname is not None and alias.asname == alias.name:
                    names.add(alias.asname)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                # `import a.b as a.b` is impossible; only `import x as x` counts.
                if alias.asname is not None and alias.asname == alias.name:
                    names.add(alias.asname)
    return frozenset(names)


def collect_doors(
    sources_by_module: Mapping[str, str],
    files_by_module: Mapping[str, Path],
) -> dict[str, frozenset[str]]:
    """Return every package that declares a door, mapped to its published names.

    ``__all__`` wins when present; otherwise the PEP 484 redundant-alias
    re-exports are used. A package that does neither has no door: it makes no
    promise, so nothing is enforced against it.

    Only ``__init__.py`` files count: a door belongs to a *package*, which is
    the unit consumers import. An ``__all__`` in a plain module governs
    ``import *`` semantics only and is deliberately ignored here.
    """
    doors: dict[str, frozenset[str]] = {}
    for module, source in sources_by_module.items():
        file = files_by_module.get(module)
        if file is None or file.name != "__init__.py":
            continue
        exported = door_of(source)
        if exported is not None:
            doors[module] = exported
    return doors


def door_of(source: str) -> frozenset[str] | None:
    """Return the door declared by one ``__init__.py`` source, or ``None``."""
    exported = collect_exports(source)
    if exported is not None:
        return exported
    return collect_explicit_reexports(source) or None


def is_inside(module: str, package: str) -> bool:
    """True when ``module`` is ``package`` itself or lives under it."""
    return module == package or module.startswith(package + ".")


def enclosing_doors(module: str, doors: Iterable[str]) -> list[str]:
    """Return the doors enclosing ``module``, innermost first.

    ``flask.json.tag`` under doors ``{flask, flask.json}`` yields
    ``["flask.json", "flask"]`` — the walls an outside importer must cross,
    nearest one first.
    """
    enclosing = [door for door in doors if is_inside(module, door)]
    return sorted(enclosing, key=lambda door: door.count("."), reverse=True)
