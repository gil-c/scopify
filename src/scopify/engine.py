"""High-level orchestrator: discover → parse → collect → enforce.

Two entry points are exposed:

* :func:`check_project` — full project scan, used by the CLI.
* :func:`build_index` + :func:`check_source` — incremental API used by the
  LSP server to re-check a single buffer on every keystroke without
  re-walking the whole project.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from scopify.config import ScopifyConfig, load_config
from scopify.diagnostics import Diagnostic
from scopify.discovery import discover_python_files
from scopify.exports import collect_doors
from scopify.imports import ImportRef, collect_imports
from scopify.markers import Visibility
from scopify.modules import module_name_for
from scopify.reexports import compute_reexports
from scopify.rules import access as access_rule
from scopify.rules import api as api_rule
from scopify.rules import dynamic as dynamic_rule
from scopify.rules import naming as naming_rule
from scopify.rules import private as private_rule
from scopify.rules import zones as zones_rule
from scopify.suppression import filter_suppressed
from scopify.symbols import Symbol, collect_symbols
from scopify.usages import collect_usages


@dataclass
class ProjectIndex:
    """Pre-computed view of a project: file ↔ module mapping and symbols."""

    root: Path
    files_by_module: dict[str, Path] = field(default_factory=dict)
    modules_by_file: dict[Path, str] = field(default_factory=dict)
    symbols_by_module: dict[str, dict[str, Symbol]] = field(default_factory=dict)
    imports_by_module: dict[str, list[ImportRef]] = field(default_factory=dict)
    # Published API surface per package: module -> names listed in its
    # ``__init__.py`` ``__all__`` (see scopify.exports). Only packages that
    # actually declare one appear here.
    doors: dict[str, frozenset[str]] = field(default_factory=dict)
    # Live source text per module, kept around so inline
    # ``# scopify: ignore`` comments can be resolved against the same
    # content the diagnostics were computed from (see scopify.suppression).
    sources_by_module: dict[str, str] = field(default_factory=dict)
    # Per-file diagnostics from rules that only need one file's AST (PA01x, SC003).
    dynamic_diagnostics_by_module: dict[str, list[Diagnostic]] = field(default_factory=dict)
    naming_diagnostics_by_module: dict[str, list[Diagnostic]] = field(default_factory=dict)
    # Visibility assumed for undecorated symbols (see scopify.config).
    default_visibility: Visibility = Visibility.PUBLIC
    # Explicit project boundaries for @internal (see scopify.config / modules).
    roots: tuple[str, ...] = ()
    disabled_rules: frozenset[str] = field(default_factory=frozenset)
    # Per-rule severity overrides from config (rule code → "error"/"warning"/"hint"/"none").
    severity_overrides: dict[str, str] = field(default_factory=dict)
    # The config as declared, kept whole so zone rules can read [tool.scopify.zones].
    config: ScopifyConfig = field(default_factory=ScopifyConfig)


def _index_symbols(
    symbols: list[Symbol], default_visibility: Visibility
) -> tuple[dict[str, Symbol], dict[str, dict[str, Symbol]]]:
    """Split parsed symbols into module-scope ones and per-class member maps.

    Module-scope symbols (functions, classes, module attributes) are
    addressable by ``from mod import X``. Anything nested under a class
    (methods, class attributes — including nested classes) is grouped by its
    owning class' qualname, keyed relative to the module, so the caller can
    register it under a synthetic ``"module.ClassName"`` scope and let
    ``usages.collect_usages`` resolve ``instance.member``/``Class.member``
    access sites the same way it resolves plain module imports.
    """
    top_level: dict[str, Symbol] = {}
    nested: dict[str, dict[str, Symbol]] = {}
    for s in symbols:
        if s.visibility is None:
            s = replace(s, visibility=default_visibility, explicit=False)
        if s.kind in ("function", "class", "attribute") and "." not in s.qualname:
            top_level[s.name] = s
        elif "." in s.qualname:
            owner = s.qualname.rsplit(".", 1)[0]
            nested.setdefault(owner, {})[s.name] = s
    return top_level, nested


def _parse_file(
    source: str, module: str, default_visibility: Visibility, *, is_package: bool = False
) -> tuple[dict[str, Symbol], dict[str, dict[str, Symbol]], list[ImportRef]]:
    symbols = collect_symbols(source, module=module)
    imports = collect_imports(source, module=module, is_package=is_package)
    top_level, nested = _index_symbols(symbols, default_visibility)
    return top_level, nested, imports


def build_index(root: Path, config: ScopifyConfig | None = None) -> ProjectIndex:
    """Scan ``root``, parse every file once, return a reusable index."""
    root = Path(root).resolve()
    if config is None:
        config = load_config(root)
    index = ProjectIndex(
        root=root,
        default_visibility=config.default_visibility,
        roots=config.roots,
        disabled_rules=config.disabled_rules,
        severity_overrides=config.severity,
        config=config,
    )
    for file in discover_python_files(root):
        module = module_name_for(file, root)
        if module is None:
            continue
        file = file.resolve()
        index.files_by_module[module] = file
        index.modules_by_file[file] = module
        try:
            source = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        index.sources_by_module[module] = source
        top_level, nested, imports = _parse_file(
            source, module, index.default_visibility, is_package=file.name == "__init__.py"
        )
        index.symbols_by_module[module] = top_level
        for class_qualname, members in nested.items():
            index.symbols_by_module[f"{module}.{class_qualname}"] = members
        index.imports_by_module[module] = imports
        index.dynamic_diagnostics_by_module[module] = dynamic_rule.check(source, module, file)
        index.naming_diagnostics_by_module[module] = naming_rule.check(source, module, file)

    # Second pass: attribute-access usages (module-qualified access, class
    # members) need every module/class scope discovered above to resolve
    # against, so they run once the whole project has been parsed.
    known_scopes = set(index.symbols_by_module.keys())
    for module, source in index.sources_by_module.items():
        usage_refs = collect_usages(source, module, known_scopes)
        if usage_refs:
            index.imports_by_module[module].extend(usage_refs)

    index.doors = collect_doors(index.sources_by_module, index.files_by_module)
    return index


def _with_reexports(
    symbols_by_module: Mapping[str, Mapping[str, Symbol]],
    imports_by_module: Mapping[str, list[ImportRef]],
    files_by_module: Mapping[str, Path],
) -> dict[str, dict[str, Symbol]]:
    """Overlay symbols promoted by ``__init__.py`` re-exports (Phase 3).

    Computed fresh each time rather than mutated into the index, so a stale
    promotion never lingers across incremental LSP re-checks.
    """
    promoted = compute_reexports(imports_by_module, symbols_by_module, files_by_module)
    if not promoted:
        return {module: dict(symbols) for module, symbols in symbols_by_module.items()}
    combined = {module: dict(symbols) for module, symbols in symbols_by_module.items()}
    for module, symbols in promoted.items():
        combined.setdefault(module, {}).update(symbols)
    return combined


def _apply_severity_overrides(
    diagnostics: list[Diagnostic],
    severity_overrides: dict[str, str],
) -> list[Diagnostic]:
    """Apply per-rule severity overrides from config.

    Rules mapped to ``"none"`` are dropped (equivalent to ``disabled_rules``).
    Other overrides replace the diagnostic's severity in-place (producing a new
    frozen instance).
    """
    if not severity_overrides:
        return diagnostics
    result: list[Diagnostic] = []
    for d in diagnostics:
        level = severity_overrides.get(d.code)
        if level is None:
            result.append(d)
        elif level == "none":
            pass  # silenced
        else:
            from dataclasses import replace as dc_replace
            result.append(dc_replace(d, severity=level))  # type: ignore[arg-type]
    return result


def _run_rules(
    imports: list[ImportRef],
    symbols_by_module: Mapping[str, Mapping[str, Symbol]],
    files_by_module: Mapping[str, Path],
    dynamic_diagnostics_by_module: Mapping[str, list[Diagnostic]],
    naming_diagnostics_by_module: Mapping[str, list[Diagnostic]],
    roots: tuple[str, ...] = (),
    disabled_rules: frozenset[str] = frozenset(),
    severity_overrides: dict[str, str] | None = None,
    doors: Mapping[str, frozenset[str]] | None = None,
    raw_symbols_by_module: Mapping[str, Mapping[str, Symbol]] | None = None,
    imports_by_module: Mapping[str, list[ImportRef]] | None = None,
    config: ScopifyConfig | None = None,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if config is not None:
        diagnostics.extend(zones_rule.check(config, files_by_module))
    diagnostics.extend(access_rule.check(imports, symbols_by_module, files_by_module, roots))
    diagnostics.extend(private_rule.check(imports, symbols_by_module, files_by_module))
    if doors:
        known_modules = set(files_by_module)
        diagnostics.extend(
            api_rule.check_reach(imports, doors, files_by_module, known_modules)
        )
        diagnostics.extend(
            api_rule.check_door(
                doors,
                raw_symbols_by_module if raw_symbols_by_module is not None else symbols_by_module,
                imports_by_module or {},
                files_by_module,
                known_modules,
            )
        )
    for diags in dynamic_diagnostics_by_module.values():
        diagnostics.extend(diags)
    for diags in naming_diagnostics_by_module.values():
        diagnostics.extend(diags)
    if disabled_rules:
        diagnostics = [d for d in diagnostics if d.code not in disabled_rules]
    if severity_overrides:
        diagnostics = _apply_severity_overrides(diagnostics, severity_overrides)
    return diagnostics


def check_project(root: Path, config: ScopifyConfig | None = None) -> list[Diagnostic]:
    """Run all enabled rules on the project rooted at ``root``.

    ``config`` may be supplied by the CLI (or tests) to override or bypass the
    on-disk ``scopify.toml`` / ``pyproject.toml``.  When ``None`` the config
    is loaded from disk as usual.
    """
    index = build_index(root, config=config)
    all_imports: list[ImportRef] = []
    for refs in index.imports_by_module.values():
        all_imports.extend(refs)
    combined_symbols = _with_reexports(
        index.symbols_by_module, index.imports_by_module, index.files_by_module
    )
    diagnostics = _run_rules(
        all_imports,
        combined_symbols,
        index.files_by_module,
        index.dynamic_diagnostics_by_module,
        index.naming_diagnostics_by_module,
        index.roots,
        index.disabled_rules,
        index.severity_overrides,
        index.doors,
        index.symbols_by_module,
        index.imports_by_module,
        index.config,
    )
    return filter_suppressed(diagnostics, index.sources_by_module, index.modules_by_file)


def check_source(
    index: ProjectIndex,
    file_path: Path,
    source: str | None = None,
) -> list[Diagnostic]:
    """Re-check a single buffer against a pre-built ``index``.

    ``source`` is the live editor content; when ``None`` we read from disk.
    Only diagnostics whose location is inside ``file_path`` are returned.
    """
    file_path = Path(file_path).resolve()
    module = index.modules_by_file.get(file_path)
    if module is None:
        module = module_name_for(file_path, index.root)
        if module is None:
            return []
        index.files_by_module[module] = file_path
        index.modules_by_file[file_path] = module

    if source is None:
        try:
            source = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []

    # Drop this module's previous synthetic class-member scopes before
    # re-registering the fresh ones parsed below.
    stale_prefix = f"{module}."
    for key in [k for k in index.symbols_by_module if k.startswith(stale_prefix)]:
        del index.symbols_by_module[key]

    top_level, nested, imports = _parse_file(
        source, module, index.default_visibility, is_package=file_path.name == "__init__.py"
    )
    # Update the live index so cross-file checks see the latest version.
    index.symbols_by_module[module] = top_level
    for class_qualname, members in nested.items():
        index.symbols_by_module[f"{module}.{class_qualname}"] = members
    index.sources_by_module[module] = source
    index.dynamic_diagnostics_by_module[module] = dynamic_rule.check(source, module, file_path)
    index.naming_diagnostics_by_module[module] = naming_rule.check(source, module, file_path)

    known_scopes = set(index.symbols_by_module.keys())
    imports.extend(collect_usages(source, module, known_scopes))
    index.imports_by_module[module] = imports

    # Editing an ``__init__.py`` can add, remove or change a door.
    if file_path.name == "__init__.py":
        from scopify.exports import door_of

        exported = door_of(source)
        if exported is None:
            index.doors.pop(module, None)
        else:
            index.doors[module] = exported

    all_imports: list[ImportRef] = []
    for refs in index.imports_by_module.values():
        all_imports.extend(refs)
    combined_symbols = _with_reexports(
        index.symbols_by_module, index.imports_by_module, index.files_by_module
    )
    diagnostics = _run_rules(
        all_imports,
        combined_symbols,
        index.files_by_module,
        index.dynamic_diagnostics_by_module,
        index.naming_diagnostics_by_module,
        index.roots,
        index.disabled_rules,
        index.severity_overrides,
        index.doors,
        index.symbols_by_module,
        index.imports_by_module,
    )
    diagnostics = filter_suppressed(diagnostics, index.sources_by_module, index.modules_by_file)
    return [d for d in diagnostics if d.file == file_path]