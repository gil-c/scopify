"""Map source files to dotted module names relative to a project root.

The mapping treats any directory containing an ``__init__.py`` as a package.
Files outside any package are exposed as their stem (top-level modules).
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


def module_name_for(path: Path, root: Path) -> str | None:
    """Return the dotted module name of ``path`` relative to ``root``.

    Returns ``None`` if ``path`` is not inside ``root`` or not a ``.py`` file.
    """
    path = Path(path).resolve()
    root = Path(root).resolve()
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    if rel.suffix != ".py":
        return None

    parts = list(rel.parts)
    # Drop trailing __init__.py — the package itself is the module.
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][: -len(".py")]
    if not parts:
        return None
    return ".".join(parts)


def package_of(module: str) -> str:
    """Return the immediate parent package of a dotted module name.

    Top-level modules are considered to be their own package.
    """
    if "." not in module:
        return module
    return module.rsplit(".", 1)[0]


def top_level_package(module: str, roots: Sequence[str] = ()) -> str:
    """Return the *project* boundary used to scope ``@internal``.

    ``@internal`` means "anywhere inside my own project", so this boundary is
    the distributed unit — normally the top-level package. ``roots`` is what
    a monorepo shipping several distributions uses to keep them apart.

    Without ``roots`` this is just the first dotted segment — a heuristic
    that breaks when the analysis root isn't the direct parent of the
    packages (e.g. a ``src/`` layout scanned from the repo root, which would
    otherwise collapse every package under a shared ``"src"`` segment).

    When ``roots`` is given (``[tool.scopify] roots = [...]`` in config),
    it's matched as the longest dotted prefix of ``module`` and returned
    verbatim, so unrelated sibling packages under the same intermediate
    directory stay properly separated.
    """
    if roots:
        for root in sorted(roots, key=len, reverse=True):
            if module == root or module.startswith(root + "."):
                return root
    return module.split(".", 1)[0]

