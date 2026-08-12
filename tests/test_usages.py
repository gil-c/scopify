"""Direct unit tests for scopify.usages (attribute-access resolution)."""
from scopify.usages import _flatten_attribute, collect_usages


def test_syntax_error_returns_empty():
    assert collect_usages("def f(:", module="m", known_scopes=set()) == []


def test_call_result_attribute_is_not_a_plain_chain():
    # `f().attr` — the base is a Call, not a Name, so it cannot be flattened
    # into a dotted chain and must be ignored rather than crash.
    import ast

    tree = ast.parse("f().attr\n")
    attr_node = tree.body[0].value
    assert _flatten_attribute(attr_node) is None


def test_bare_import_qualified_attribute_usage_is_resolved():
    source = "import alpha.core\nalpha.core.helper()\n"
    usages = collect_usages(source, module="beta.user", known_scopes={"alpha.core"})
    assert len(usages) == 1
    assert usages[0].from_module == "alpha.core"
    assert usages[0].imported_name == "helper"
    assert usages[0].importer == "beta.user"


def test_aliased_module_import_qualified_attribute_usage_is_resolved():
    source = "import alpha.core as ac\nac.helper()\n"
    usages = collect_usages(source, module="beta.user", known_scopes={"alpha.core"})
    assert len(usages) == 1
    assert usages[0].from_module == "alpha.core"
    assert usages[0].imported_name == "helper"


def test_from_import_of_class_then_instance_member_access_is_resolved():
    source = "from alpha.core import Widget\nw = Widget()\nw.helper()\n"
    usages = collect_usages(
        source, module="beta.user", known_scopes={"alpha.core.Widget"}
    )
    assert len(usages) == 1
    assert usages[0].from_module == "alpha.core.Widget"
    assert usages[0].imported_name == "helper"


def test_direct_class_attribute_access_without_instantiation_is_resolved():
    source = "from alpha.core import Widget\nWidget.helper()\n"
    usages = collect_usages(
        source, module="beta.user", known_scopes={"alpha.core.Widget"}
    )
    assert len(usages) == 1
    assert usages[0].imported_name == "helper"


def test_unresolvable_name_is_silently_ignored():
    # `unknown` was never imported/assigned from a known scope.
    source = "unknown.attr()\n"
    assert collect_usages(source, module="m", known_scopes={"alpha.core"}) == []


def test_unknown_scope_is_silently_ignored():
    # `os.path` is a real qualified access, but "os" isn't a known project scope.
    source = "import os.path\nos.path.join()\n"
    assert collect_usages(source, module="m", known_scopes={"alpha.core"}) == []


def test_star_import_does_not_seed_a_name_binding():
    source = "from alpha.core import *\nhelper()\n"
    # `*` can't be resolved to a specific bound name, so no usage is produced
    # (and this must not raise).
    assert collect_usages(source, module="m", known_scopes={"alpha.core"}) == []


def test_relative_import_of_class_then_member_access_is_resolved():
    source = "from .core import Widget\nWidget.helper()\n"
    usages = collect_usages(
        source, module="alpha.user", known_scopes={"alpha.core.Widget"}
    )
    assert len(usages) == 1
    assert usages[0].from_module == "alpha.core.Widget"


def test_tuple_unpacking_assignment_does_not_seed_instance_binding():
    # `a, b = Widget(), Widget()` — targets aren't a plain Name, so this must
    # be skipped rather than mis-tracked or crash.
    source = (
        "from alpha.core import Widget\n"
        "a, b = Widget(), Widget()\n"
        "a.helper()\n"
    )
    usages = collect_usages(
        source, module="beta.user", known_scopes={"alpha.core.Widget"}
    )
    assert usages == []


def test_instance_attribute_chain_shorter_than_two_is_ignored():
    # A bare Name (no attribute at all) never reaches the attribute check.
    source = "from alpha.core import Widget\nWidget\n"
    assert collect_usages(
        source, module="beta.user", known_scopes={"alpha.core.Widget"}
    ) == []


def test_relative_import_beyond_package_depth_is_skipped_in_usages():
    # Excessive leading dots relative to the importing module's own depth
    # cannot be resolved; collect_usages must skip rather than crash.
    source = "from ...pkg import Widget\nWidget.helper()\n"
    assert collect_usages(source, module="mod", known_scopes={"pkg.Widget"}) == []


def test_call_on_non_attribute_expression_does_not_seed_a_binding():
    # `x = (a + b)()` — the call target is a BinOp, not a Name/Attribute
    # chain, so it can't be resolved to a known scope.
    source = "from alpha.core import Widget\na = 1\nb = 2\nx = (a + b)()\nx.helper()\n"
    assert collect_usages(
        source, module="beta.user", known_scopes={"alpha.core.Widget"}
    ) == []


def test_call_of_unresolvable_name_does_not_seed_a_binding():
    # `x = unknown_factory()` — `unknown_factory` was never imported/assigned
    # from a known scope, so the resulting binding must stay unresolved.
    source = "x = unknown_factory()\nx.helper()\n"
    assert collect_usages(
        source, module="beta.user", known_scopes={"alpha.core.Widget"}
    ) == []


def test_attribute_access_on_call_result_is_ignored():
    # `factory().attr` — the base of the attribute chain is a Call, not a
    # Name, so it can't be flattened and must be silently skipped end-to-end.
    source = "factory().attr\n"
    assert collect_usages(source, module="m", known_scopes={"alpha.core"}) == []
