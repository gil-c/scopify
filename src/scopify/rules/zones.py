"""SC020 / SC021 — declared zones and the code they are supposed to cover.

Both rules are silent unless the project declares at least one zone under
``[tool.scopify.zones]``. That condition is not a convenience: without it,
upgrading scopify would light up every project that never asked for zones,
and a linter that turns a green repository red on its own is a linter people
uninstall.

SC020 fires once per package that no declared zone claims, anchored on that
package's ``__init__.py``. Adding a folder can therefore dirty exactly one
line — the folder you added — instead of the whole project.

SC021 is the mirror: a zone declared in ``pyproject.toml`` whose patterns
match nothing. That is usually a rename nobody propagated, and it is worth
saying, because a zone matching nothing silently enforces nothing.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from scopify.config import ScopifyConfig
from scopify.diagnostics import Diagnostic

UNCLAIMED = "SC020"
EMPTY_ZONE = "SC021"


def _anchor(package: str, files_by_module: Mapping[str, Path]) -> Path | None:
    """The file a package-level complaint should land on."""
    return files_by_module.get(package)


def _packages(files_by_module: Mapping[str, Path]) -> dict[str, list[str]]:
    """Group modules by the package they live in.

    A package's own ``__init__`` counts as part of itself, not of its
    parent. That is what keeps the promise: adding one folder dirties one
    line, the added folder's, and never the line of the package above it.
    """
    grouped: dict[str, list[str]] = {}
    for module, file in files_by_module.items():
        package = (
            module
            if file.name == "__init__.py"
            else module.rpartition(".")[0] or module
        )
        grouped.setdefault(package, []).append(module)
    return grouped


def check(
    config: ScopifyConfig,
    files_by_module: Mapping[str, Path],
) -> list[Diagnostic]:
    if not config.zones:
        return []

    diagnostics: list[Diagnostic] = []
    for package, modules in sorted(_packages(files_by_module).items()):
        unclaimed = [m for m in modules if config.zone_of(m) is None]
        if not unclaimed:
            continue
        file = _anchor(package, files_by_module) or files_by_module[sorted(unclaimed)[0]]
        missing = len(unclaimed)
        detail = (
            f"{missing} module(s)" if missing > 1 else f"'{sorted(unclaimed)[0]}'"
        )
        diagnostics.append(
            Diagnostic(
                code=UNCLAIMED,
                message=(
                    f"package '{package}' belongs to no declared zone "
                    f"({detail} unclaimed). Add it to [tool.scopify.zones] "
                    f"in pyproject.toml, or run 'scopify zones --init'."
                ),
                file=file,
                line=1,
                column=0,
                symbol=package,
                severity="error",
            )
        )

    matched = {
        name
        for module in files_by_module
        if (name := config.zone_of(module)) is not None
    }
    config_file = _config_file(files_by_module)
    for name in sorted(set(config.zones) - matched):
        if config_file is None:
            continue
        patterns = ", ".join(config.zones[name].modules)
        diagnostics.append(
            Diagnostic(
                code=EMPTY_ZONE,
                message=(
                    f"zone '{name}' matches no module in this project "
                    f"(patterns: {patterns}). A renamed package, or a zone "
                    f"that outlived its code."
                ),
                file=config_file,
                line=1,
                column=0,
                symbol=name,
                severity="warning",
            )
        )
    return diagnostics


def _config_file(files_by_module: Mapping[str, Path]) -> Path | None:
    """Where to hang a complaint about the declaration itself."""
    for file in files_by_module.values():
        for folder in [file.parent, *file.parents]:
            candidate = folder / "pyproject.toml"
            if candidate.is_file():
                return candidate
        break
    return None
