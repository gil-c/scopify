"""Tests for __init__.py re-export promotion (scopify.reexports)."""
from __future__ import annotations

from pathlib import Path

from scopify.imports import ImportRef
from scopify.markers import Visibility
from scopify.reexports import compute_reexports
from scopify.symbols import Symbol


def _import(importer: str, from_module: str, name: str, alias: str | None = None) -> ImportRef:
    return ImportRef(
        importer=importer,
        from_module=from_module,
        imported_name=name,
        alias=alias,
        lineno=1,
        col_offset=0,
    )


def _symbol(module: str, name: str, visibility: Visibility | None) -> Symbol:
    return Symbol(
        name=name,
        qualname=name,
        module=module,
        kind="function",
        visibility=visibility,
        lineno=1,
        col_offset=0,
    )


def test_internal_symbol_reexported_via_init_is_promoted_to_public():
    imports_by_module = {"alpha": [_import("alpha", "alpha.core", "helper")]}
    symbols_by_module = {
        "alpha.core": {"helper": _symbol("alpha.core", "helper", Visibility.INTERNAL)},
    }
    files_by_module = {"alpha": Path("alpha/__init__.py")}

    promoted = compute_reexports(imports_by_module, symbols_by_module, files_by_module)

    assert "alpha" in promoted
    assert promoted["alpha"]["helper"].visibility is Visibility.PUBLIC
    assert promoted["alpha"]["helper"].module == "alpha"


def test_import_outside_init_does_not_promote():
    # Same import, but from a regular module, not __init__.py.
    imports_by_module = {"alpha.user": [_import("alpha.user", "alpha.core", "helper")]}
    symbols_by_module = {
        "alpha.core": {"helper": _symbol("alpha.core", "helper", Visibility.INTERNAL)},
    }
    files_by_module = {"alpha.user": Path("alpha/user.py")}

    promoted = compute_reexports(imports_by_module, symbols_by_module, files_by_module)
    assert promoted == {}


def test_already_public_symbol_is_still_promoted_for_reexport_consistency():
    # Harmless duplicate promotion: keeps the re-exporting module's symbol
    # table consistent (useful for future audit/suggestion tooling), and is
    # required so re-export chains through nested packages work (see below).
    imports_by_module = {"alpha": [_import("alpha", "alpha.core", "api")]}
    symbols_by_module = {
        "alpha.core": {"api": _symbol("alpha.core", "api", Visibility.PUBLIC)},
    }
    files_by_module = {"alpha": Path("alpha/__init__.py")}

    promoted = compute_reexports(imports_by_module, symbols_by_module, files_by_module)
    assert promoted["alpha"]["api"].visibility is Visibility.PUBLIC


def test_private_symbol_is_not_promoted():
    # A private re-export is already invalid at its own import site (SC002);
    # this module must not additionally promote it to public.
    imports_by_module = {"alpha": [_import("alpha", "alpha.core", "_secret")]}
    symbols_by_module = {
        "alpha.core": {"_secret": _symbol("alpha.core", "_secret", Visibility.PRIVATE)},
    }
    files_by_module = {"alpha": Path("alpha/__init__.py")}

    promoted = compute_reexports(imports_by_module, symbols_by_module, files_by_module)
    assert promoted == {}


def test_alias_reexport_uses_exposed_name():
    imports_by_module = {
        "alpha": [_import("alpha", "alpha.core", "helper", alias="do_it")],
    }
    symbols_by_module = {
        "alpha.core": {"helper": _symbol("alpha.core", "helper", Visibility.INTERNAL)},
    }
    files_by_module = {"alpha": Path("alpha/__init__.py")}

    promoted = compute_reexports(imports_by_module, symbols_by_module, files_by_module)
    assert "do_it" in promoted["alpha"]
    assert "helper" not in promoted.get("alpha", {})


def test_reexport_chains_through_nested_packages():
    # alpha/sub/__init__.py re-exports from alpha.sub.core;
    # alpha/__init__.py re-exports from alpha.sub (the re-export itself).
    imports_by_module = {
        "alpha.sub": [_import("alpha.sub", "alpha.sub.core", "helper")],
        "alpha": [_import("alpha", "alpha.sub", "helper")],
    }
    symbols_by_module = {
        "alpha.sub.core": {"helper": _symbol("alpha.sub.core", "helper", Visibility.INTERNAL)},
    }
    files_by_module = {
        "alpha.sub": Path("alpha/sub/__init__.py"),
        "alpha": Path("alpha/__init__.py"),
    }

    promoted = compute_reexports(imports_by_module, symbols_by_module, files_by_module)
    assert promoted["alpha.sub"]["helper"].visibility is Visibility.PUBLIC
    assert promoted["alpha"]["helper"].visibility is Visibility.PUBLIC


def test_explicit_declaration_is_never_overwritten_by_promotion():
    # alpha/__init__.py both defines its own `helper` AND re-exports one from
    # alpha.core under the same name: the explicit declaration wins.
    imports_by_module = {"alpha": [_import("alpha", "alpha.core", "helper")]}
    symbols_by_module = {
        "alpha": {"helper": _symbol("alpha", "helper", Visibility.PRIVATE)},
        "alpha.core": {"helper": _symbol("alpha.core", "helper", Visibility.INTERNAL)},
    }
    files_by_module = {"alpha": Path("alpha/__init__.py")}

    promoted = compute_reexports(imports_by_module, symbols_by_module, files_by_module)
    assert promoted == {}


def test_unresolvable_target_module_is_ignored():
    imports_by_module = {"alpha": [_import("alpha", "external_pkg", "thing")]}
    symbols_by_module: dict[str, dict[str, Symbol]] = {}
    files_by_module = {"alpha": Path("alpha/__init__.py")}

    promoted = compute_reexports(imports_by_module, symbols_by_module, files_by_module)
    assert promoted == {}
