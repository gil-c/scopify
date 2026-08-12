"""Direct unit tests for rules/access.py and rules/private.py, exercising
the defensive branches that check_project's normal flow can't reach (an
import whose importer module has no entry in files_by_module)."""
from scopify.imports import ImportRef
from scopify.markers import Visibility
from scopify.rules import access as access_rule
from scopify.rules import private as private_rule
from scopify.symbols import Symbol


def _symbol(name, module, visibility, qualname=None):
    return Symbol(
        name=name,
        qualname=qualname or name,
        module=module,
        kind="function",
        visibility=visibility,
        lineno=1,
        col_offset=0,
    )


def test_access_rule_skips_import_with_no_known_file_for_importer():
    imp = ImportRef(
        importer="unknown.importer",
        from_module="alpha.core",
        imported_name="helper",
        alias=None,
        lineno=1,
        col_offset=0,
    )
    symbols_by_module = {
        "alpha.core": {"helper": _symbol("helper", "alpha.core", Visibility.INTERNAL)}
    }
    # `files_by_module` deliberately has no entry for "unknown.importer".
    diagnostics = access_rule.check(
        [imp], symbols_by_module, files_by_module={}
    )
    assert diagnostics == []


def test_access_rule_ignores_unresolvable_from_module():
    imp = ImportRef(
        importer="beta.user",
        from_module="external.package",
        imported_name="thing",
        alias=None,
        lineno=1,
        col_offset=0,
    )
    diagnostics = access_rule.check([imp], symbols_by_module={}, files_by_module={})
    assert diagnostics == []


def test_access_rule_ignores_import_of_unknown_symbol_name():
    imp = ImportRef(
        importer="beta.user",
        from_module="alpha.core",
        imported_name="missing",
        alias=None,
        lineno=1,
        col_offset=0,
    )
    symbols_by_module = {
        "alpha.core": {"helper": _symbol("helper", "alpha.core", Visibility.INTERNAL)}
    }
    diagnostics = access_rule.check([imp], symbols_by_module, files_by_module={})
    assert diagnostics == []


def test_private_rule_skips_import_with_no_known_file_for_importer():
    imp = ImportRef(
        importer="unknown.importer",
        from_module="alpha.core",
        imported_name="secret",
        alias=None,
        lineno=1,
        col_offset=0,
    )
    symbols_by_module = {
        "alpha.core": {"secret": _symbol("secret", "alpha.core", Visibility.PRIVATE)}
    }
    diagnostics = private_rule.check([imp], symbols_by_module, files_by_module={})
    assert diagnostics == []


def test_private_rule_uses_symbol_module_not_raw_from_module():
    # Simulates a synthetic class-member scope lookup where `from_module` is
    # the "module.Class" key but the underlying symbol's own `.module` is the
    # plain module — same-module comparison must use the latter.
    imp = ImportRef(
        importer="alpha.core",
        from_module="alpha.core.Widget",
        imported_name="secret",
        alias=None,
        lineno=1,
        col_offset=0,
    )
    symbols_by_module = {
        "alpha.core.Widget": {
            "secret": _symbol(
                "secret", "alpha.core", Visibility.PRIVATE, qualname="Widget.secret"
            )
        }
    }
    diagnostics = private_rule.check(
        [imp], symbols_by_module, files_by_module={"alpha.core": "core.py"}
    )
    assert diagnostics == []
