"""SC001 — using an ``@internal`` symbol from outside the scope it allows.

The foundational rule of Scopify, and the one place where zones and
per-symbol visibility finally meet.

Without ``[tool.scopify.zones]``, the boundary is the project: ``@internal``
means "usable anywhere inside my own project, promised to nobody outside",
and this behaves exactly as it did before zones existed.

Declare zones and the boundary tightens to the zone that defines the symbol.
That is a deliberate hardening — it lights up couplings that were always
there and that nothing was naming. Each one is answerable in one of three
ways, all cheap: widen the symbol (``@internal(including=["other"])``, or
``including="*"`` for the whole project), list it in the zone's ``exposes``, or
move the code. A zone's ``exposes`` covers the symbols it hands out without
touching a line of code, which is why ``scopify zones --init`` produces a
declaration that reports nothing on day one.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from scopify.config import ScopifyConfig
from scopify.diagnostics import Diagnostic
from scopify.imports import ImportRef
from scopify.markers import EVERY_ZONE, Visibility
from scopify.modules import top_level_package
from scopify.symbols import Symbol

CODE = "SC001"


def _owning_module(target: str, known: Mapping[str, object]) -> str:
    """The real module behind an import target.

    Member access is recorded against ``module.attr`` chains, which are not
    modules. Walk the dots back until something real appears; fall back to
    the target itself so behaviour is unchanged when nothing matches.
    """
    candidate = target
    while candidate:
        if candidate in known:
            return candidate
        candidate = candidate.rpartition(".")[0]
    return target


def check(
    imports: Iterable[ImportRef],
    symbols_by_module: Mapping[str, Mapping[str, Symbol]],
    files_by_module: Mapping[str, Path],
    roots: Iterable[str] = (),
    config: ScopifyConfig | None = None,
) -> list[Diagnostic]:
    zones = config.zones if config is not None else {}
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
        here = top_level_package(imp.importer, roots)
        there = top_level_package(symbol.module, roots)
        if not zones:
            if here == there:
                continue  # same project — that is exactly what @internal allows
            where, allowed = f"project '{here}'", "its own project"
        else:
            owner = _owning_module(imp.from_module, symbols_by_module)
            home = config.zone_of(owner) if config is not None else None
            user = config.zone_of(imp.importer) if config is not None else None
            if home is None or user is None:
                continue  # SC020 already complains about undeclared packages
            reaches = (*symbol.shared_with, *zones[home].shared_zones(imp.imported_name))
            if user == home or EVERY_ZONE in reaches or user in reaches:
                continue
            if imp.imported_name in zones[home].exposes:
                continue  # the zone publishes it, so anyone may take it
            named = ", ".join(f"'{z}'" for z in dict.fromkeys((home, *reaches)))
            where = f"zone '{user}'"
            allowed = f"zone {named}" if not reaches else f"zones {named}"
        file = files_by_module.get(imp.importer)
        if file is None:
            continue
        diagnostics.append(
            Diagnostic(
                code=CODE,
                message=(
                    f"'{imp.imported_name}' is marked @internal in "
                    f"'{imp.from_module}' and is limited to {allowed}, "
                    f"so {where} cannot use it."
                ),
                file=file,
                line=imp.lineno,
                column=imp.col_offset,
                symbol=imp.imported_name,
            )
        )
    return diagnostics


