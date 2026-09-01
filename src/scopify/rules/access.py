"""SC001 — cross-project import of a symbol marked ``@internal``.

This is the foundational rule of Scopify. ``@internal`` means "usable
anywhere inside my own project, promised to nobody outside", so this rule
walks every import site and reports those resolving to an ``@internal``
symbol that belongs to a *different* project (see
``scopify.modules.top_level_package`` for how that boundary is determined).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from scopify.diagnostics import Diagnostic
from scopify.imports import ImportRef
from scopify.markers import Visibility
from scopify.modules import top_level_package
from scopify.symbols import Symbol

CODE = "SC001"


def check(
    imports: Iterable[ImportRef],
    symbols_by_module: Mapping[str, Mapping[str, Symbol]],
    files_by_module: Mapping[str, Path],
    roots: Iterable[str] = (),
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for imp in imports:
        if imp.imported_name in (None, "*"):
            # `import pkg.mod` (bare) and star imports are handled by usages.py
            # once the accessed attribute is known; nothing to check here yet.
            continue
        target_symbols = symbols_by_module.get(imp.from_module)
        if target_symbols is None:
            continue  # external dependency or undiscovered module
        symbol = target_symbols.get(imp.imported_name)
        if symbol is None or symbol.visibility is not Visibility.INTERNAL:
            continue
        if top_level_package(imp.importer, roots) == top_level_package(symbol.module, roots):
            continue  # same project — that is exactly what @internal allows
        file = files_by_module.get(imp.importer)
        if file is None:
            continue
        diagnostics.append(
            Diagnostic(
                code=CODE,
                message=(
                    f"'{imp.imported_name}' is marked @internal in "
                    f"'{imp.from_module}' and cannot be imported from "
                    f"project '{top_level_package(imp.importer, roots)}'."
                ),
                file=file,
                line=imp.lineno,
                column=imp.col_offset,
                symbol=imp.imported_name,
            )
        )
    return diagnostics


