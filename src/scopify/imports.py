"""Extract import statements from a Python source."""
from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class ImportRef:
    importer: str            # dotted name of the importing module
    from_module: str         # dotted name of the source module
    imported_name: str | None  # imported symbol, or None for `import X`
    alias: str | None
    lineno: int
    col_offset: int


def _resolve_relative(level: int, base_module: str, target: str | None) -> str | None:
    """Resolve a `from .X import Y` style import to an absolute module name."""
    if level == 0:
        return target
    parts = base_module.split(".")
    # `from . import x` inside `pkg.mod` means `pkg`. Each extra dot pops one more.
    if level > len(parts):
        return None
    base_parts = parts[: len(parts) - level] if len(parts) > level else []
    # `from .sibling import x` inside `pkg.mod` -> `pkg.sibling`
    # base_parts should be the parent package, i.e. pop one off for the module itself,
    # then pop `level - 1` more.
    base_parts = parts[: max(0, len(parts) - level)]
    if target:
        base_parts = base_parts + [target]
    if not base_parts:
        return None
    return ".".join(base_parts)


def collect_imports(source: str, module: str) -> list[ImportRef]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    refs: list[ImportRef] = []
    for node in ast.walk(tree):
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
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_relative(node.level or 0, module, node.module)
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
                        )
                    )
                    continue
                refs.append(
                    ImportRef(
                        importer=module,
                        from_module=resolved,
                        imported_name=alias.name,
                        alias=alias.asname,
                        # Prefer the alias's own location so editors underline
                        # the imported name rather than the leading ``from``.
                        lineno=getattr(alias, "lineno", node.lineno),
                        col_offset=getattr(alias, "col_offset", node.col_offset),
                    )
                )
    return refs


