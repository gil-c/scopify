"""Re-export promotion: symbols surfaced through a package's ``__init__.py``.

Per the roadmap (Phase 3): "an ``@internal`` symbol exposed in ``__init__.py``
of a package becomes ``public`` within that package." Concretely, if
``alpha/__init__.py`` does ``from alpha.core import helper`` and ``helper``
is declared ``@internal`` in ``alpha.core``, then ``from alpha import helper``
must be importable from any other package, even though the original
declaration site is still internal.

``@private`` symbols are *not* handled here: re-exporting one from another
module is already rejected at the re-export's own import site by SC002
(cross-module access to a private symbol), so it can never reach this stage.

The promotion is computed to a fixpoint so re-exports chain through nested
packages (``alpha/sub/__init__.py`` re-exporting into ``alpha/__init__.py``).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from scopify.imports import ImportRef
from scopify.markers import Visibility
from scopify.symbols import Symbol


def compute_reexports(
    imports_by_module: Mapping[str, list[ImportRef]],
    symbols_by_module: Mapping[str, Mapping[str, Symbol]],
    files_by_module: Mapping[str, Path],
) -> dict[str, dict[str, Symbol]]:
    """Return the *additional* symbols promoted by ``__init__.py`` re-exports.

    Only ``@internal`` symbols are promoted (to ``public``, within the
    re-exporting module). The result maps module -> {exposed name -> Symbol},
    containing only newly-promoted entries (never overwriting a symbol that
    is already explicitly declared, or already promoted, under that name).
    """
    working: dict[str, dict[str, Symbol]] = {
        module: dict(symbols) for module, symbols in symbols_by_module.items()
    }

    changed = True
    while changed:
        changed = False
        for module, refs in imports_by_module.items():
            file = files_by_module.get(module)
            if file is None or file.name != "__init__.py":
                continue  # re-exports only count from a package's __init__
            for imp in refs:
                if imp.importer != module or imp.imported_name in (None, "*"):
                    continue
                target_symbols = working.get(imp.from_module)
                if not target_symbols:
                    continue
                original = target_symbols.get(imp.imported_name)
                if original is None or original.visibility is Visibility.PRIVATE:
                    continue  # private is already rejected at this import site by SC002;
                    # public/internal/default-visibility symbols are all fair game to
                    # re-export, and chaining requires re-promoting an already-promoted
                    # (now-public) symbol one level further up.
                exposed_name = imp.alias or imp.imported_name
                bucket = working.setdefault(module, {})
                if exposed_name in bucket:
                    continue
                bucket[exposed_name] = replace(
                    original,
                    name=exposed_name,
                    qualname=exposed_name,
                    module=module,
                    visibility=Visibility.PUBLIC,
                    lineno=imp.lineno,
                    col_offset=imp.col_offset,
                )
                changed = True

    promoted: dict[str, dict[str, Symbol]] = {}
    for module, symbols in working.items():
        original_symbols = symbols_by_module.get(module, {})
        diff = {name: sym for name, sym in symbols.items() if name not in original_symbols}
        if diff:
            promoted[module] = diff
    return promoted
