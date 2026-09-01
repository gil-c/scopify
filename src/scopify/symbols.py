"""Extract declared symbols and their visibility from a Python source."""
from __future__ import annotations

import ast
from dataclasses import dataclass

from scopify.markers import Visibility, get_visibility_name


@dataclass(frozen=True)
class Symbol:
    name: str
    qualname: str
    module: str
    kind: str  # "function" | "class" | "method"
    visibility: Visibility | None
    lineno: int
    col_offset: int
    # True when the visibility was written at the definition site, False when
    # it was filled in from ``default_visibility``. SC005 needs the
    # distinction: only a *declared* @internal contradicts a published name.
    explicit: bool = True


def _dotted_name(node: ast.expr) -> str:
    """Best-effort dotted name extraction for a decorator/annotation expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return _dotted_name(node.func)
    return ""


# Kept as an alias: historically decorator-only, now shared with Annotated metadata.
_decorator_name = _dotted_name


def _visibility_from_decorators(
    decorators: list, alias_to_visibility: dict[str, Visibility]
) -> Visibility | None:
    for dec in decorators:
        # Resolve via aliasing (e.g. `from scopify import internal as _hidden`)
        name = _decorator_name(dec)
        if not name:
            continue
        head = name.split(".", 1)[0]
        if head in alias_to_visibility and "." not in name:
            return alias_to_visibility[head]
        v = get_visibility_name(name)
        if v is not None:
            return Visibility(v)
    return None


def _is_annotated_subscript(node: ast.expr) -> bool:
    if not isinstance(node, ast.Subscript):
        return False
    tail = _dotted_name(node.value).rsplit(".", 1)[-1]
    return tail == "Annotated"


def _annotated_metadata(node: ast.Subscript) -> list[ast.expr]:
    """Everything after the wrapped type in ``Annotated[T, meta1, meta2, ...]``."""
    sl = node.slice
    elts = sl.elts if isinstance(sl, ast.Tuple) else [sl]
    return elts[1:]


def _visibility_from_annotation(
    annotation: ast.expr | None, alias_to_visibility: dict[str, Visibility]
) -> Visibility | None:
    """Visibility carried by ``Annotated[T, Internal]`` (or ``Public``/``Private``)."""
    if annotation is None or not _is_annotated_subscript(annotation):
        return None
    for meta in _annotated_metadata(annotation):
        name = _dotted_name(meta)
        if not name:
            continue
        head = name.split(".", 1)[0]
        if head in alias_to_visibility and "." not in name:
            return alias_to_visibility[head]
        v = get_visibility_name(name)
        if v is not None:
            return Visibility(v)
    return None


def _collect_visibility_aliases(tree: ast.AST) -> dict[str, Visibility]:
    """Find ``from scopify import internal as X`` style aliases."""
    aliases: dict[str, Visibility] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("scopify"):
            for alias in node.names:
                v = get_visibility_name(alias.name)
                if v is not None:
                    aliases[alias.asname or alias.name] = Visibility(v)
        elif isinstance(node, ast.Import):
            # `import scopify` -> use `scopify.internal` (already handled by get_visibility_name)
            pass
    return aliases


def collect_symbols(source: str, module: str) -> list[Symbol]:
    """Parse ``source`` and return the list of declared symbols."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    aliases = _collect_visibility_aliases(tree)
    symbols: list[Symbol] = []

    def visit_class(cls: ast.ClassDef, qual_prefix: str) -> None:
        qual = f"{qual_prefix}{cls.name}" if qual_prefix else cls.name
        symbols.append(
            Symbol(
                name=cls.name,
                qualname=qual,
                module=module,
                kind="class",
                visibility=_visibility_from_decorators(cls.decorator_list, aliases),
                lineno=cls.lineno,
                col_offset=cls.col_offset,
            )
        )
        for child in cls.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(
                    Symbol(
                        name=child.name,
                        qualname=f"{qual}.{child.name}",
                        module=module,
                        kind="method",
                        visibility=_visibility_from_decorators(child.decorator_list, aliases),
                        lineno=child.lineno,
                        col_offset=child.col_offset,
                    )
                )
            elif isinstance(child, ast.ClassDef):
                visit_class(child, qual + ".")
            elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                symbols.append(
                    Symbol(
                        name=child.target.id,
                        qualname=f"{qual}.{child.target.id}",
                        module=module,
                        kind="attribute",
                        visibility=_visibility_from_annotation(child.annotation, aliases),
                        lineno=child.lineno,
                        col_offset=child.col_offset,
                    )
                )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(
                Symbol(
                    name=node.name,
                    qualname=node.name,
                    module=module,
                    kind="function",
                    visibility=_visibility_from_decorators(node.decorator_list, aliases),
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                )
            )
        elif isinstance(node, ast.ClassDef):
            visit_class(node, "")
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            symbols.append(
                Symbol(
                    name=node.target.id,
                    qualname=node.target.id,
                    module=module,
                    kind="attribute",
                    visibility=_visibility_from_annotation(node.annotation, aliases),
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                )
            )

    return symbols

