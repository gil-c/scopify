"""SC004 / SC005 — enforcement of the published API surface (the "door").

These two rules implement the *door* model described in ``scopify.exports``:
a package's ``__all__`` is the list of names it promises to the outside
world. They are deliberately independent of ``@public``/``@internal``
annotations, so they produce useful results on a project that has never been
annotated at all.

* **SC004** — reaching past a door: importing, from outside a package, a name
  that the package does not publish.
* **SC005** — a door that contradicts itself: a published name that does not
  exist, or that is explicitly marked ``@internal``/``@private`` at its
  definition site.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from scopify.diagnostics import Diagnostic
from scopify.exports import enclosing_doors, is_inside
from scopify.imports import ImportRef
from scopify.markers import Visibility
from scopify.symbols import Symbol

REACH_CODE = "SC004"
DOOR_CODE = "SC005"


def check_reach(
    imports: Iterable[ImportRef],
    doors: Mapping[str, frozenset[str]],
    files_by_module: Mapping[str, Path],
    known_modules: Iterable[str] = (),
) -> list[Diagnostic]:
    """SC004 — flag imports that reach past a package's published API."""
    diagnostics: list[Diagnostic] = []
    if not doors:
        return diagnostics
    modules = set(known_modules) or set(files_by_module)

    for imp in imports:
        if imp.imported_name in (None, "*"):
            continue
        if imp.imported_name.startswith("__"):
            continue  # dunders (__version__, __all__) are metadata, not API
        if imp.from_module not in modules:
            continue  # external dependency, or a module we never parsed
        # `from pkg import submodule` is structural, not symbol access: the
        # reach is reported later, on whatever symbol is pulled out of it.
        if f"{imp.from_module}.{imp.imported_name}" in modules:
            continue

        for door in enclosing_doors(imp.from_module, doors):
            if is_inside(imp.importer, door):
                continue  # importer lives inside: no wall is crossed
            if imp.imported_name in doors[door]:
                continue  # published: the door allows it
            file = files_by_module.get(imp.importer)
            if file is None:
                break
            diagnostics.append(
                Diagnostic(
                    code=REACH_CODE,
                    severity="warning",
                    message=(
                        f"'{imp.imported_name}' is not part of the published API of "
                        f"'{door}'; importing it from '{imp.importer}' relies on "
                        "internals that the package never promised."
                    ),
                    file=file,
                    line=imp.lineno,
                    column=imp.col_offset,
                    symbol=imp.imported_name,
                )
            )
            break  # report the innermost crossed door only

    return diagnostics


def _origin_of(
    name: str,
    package: str,
    imports_by_module: Mapping[str, list[ImportRef]],
) -> tuple[str, str] | None:
    """Resolve a re-exported name to its ``(module, original name)`` origin."""
    for imp in imports_by_module.get(package, ()):
        if imp.importer != package or imp.imported_name in (None, "*"):
            continue
        if (imp.alias or imp.imported_name) == name:
            return imp.from_module, imp.imported_name  # type: ignore[return-value]
    return None


def check_door(
    doors: Mapping[str, frozenset[str]],
    symbols_by_module: Mapping[str, Mapping[str, Symbol]],
    imports_by_module: Mapping[str, list[ImportRef]],
    files_by_module: Mapping[str, Path],
    known_modules: Iterable[str] = (),
) -> list[Diagnostic]:
    """SC005 — flag a published name that is missing or declared non-public.

    ``symbols_by_module`` must be the *raw* symbol tables, before re-export
    promotion: promotion rewrites a re-exported ``@internal`` symbol to
    public, which is precisely the contradiction this rule looks for.
    """
    diagnostics: list[Diagnostic] = []
    modules = set(known_modules) or set(files_by_module)

    for package in sorted(doors):
        file = files_by_module.get(package)
        if file is None:
            continue
        own_symbols = symbols_by_module.get(package, {})
        # A star-import makes the package's contents statically unknowable,
        # so a missing name can't be distinguished from an invisible one.
        has_star = any(
            imp.imported_name == "*" for imp in imports_by_module.get(package, ())
        )

        for name in sorted(doors[package]):
            if name in own_symbols:
                origin = own_symbols[name]
            else:
                resolved = _origin_of(name, package, imports_by_module)
                if resolved is None:
                    if has_star or f"{package}.{name}" in modules or name.startswith("__"):
                        continue  # star-imported, a submodule, or a dunder
                    diagnostics.append(
                        Diagnostic(
                            code=DOOR_CODE,
                            message=(
                                f"'{name}' is published by '{package}' but is neither "
                                "defined nor imported there; the declared API surface "
                                "does not resolve."
                            ),
                            file=file,
                            line=1,
                            column=0,
                            symbol=name,
                        )
                    )
                    continue
                origin_module, origin_name = resolved
                origin = symbols_by_module.get(origin_module, {}).get(origin_name)
                if origin is None:
                    continue  # defined outside the project (a third-party re-export)

            if not origin.explicit or origin.visibility is Visibility.PUBLIC:
                continue
            if origin.visibility not in (Visibility.INTERNAL, Visibility.PRIVATE):
                continue
            marker = origin.visibility.value
            diagnostics.append(
                Diagnostic(
                    code=DOOR_CODE,
                    message=(
                        f"'{name}' is published by '{package}' but declared "
                        f"@{marker} in '{origin.module}'; the published API and the "
                        "declaration disagree."
                    ),
                    file=file,
                    line=1,
                    column=0,
                    symbol=name,
                )
            )

    return diagnostics
