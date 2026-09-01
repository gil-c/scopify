"""Import extraction from a Python source."""
from scopify.imports import collect_imports


def test_from_import_simple():
    source = "from pkg.other import helper, api\n"
    imps = collect_imports(source, module="pkg.mod")
    pairs = {(i.from_module, i.imported_name) for i in imps}
    assert pairs == {("pkg.other", "helper"), ("pkg.other", "api")}
    assert all(i.importer == "pkg.mod" for i in imps)


def test_plain_import_does_not_resolve_a_named_symbol():
    # `import pkg.other` imports a module, not a named symbol — for the POC
    # we expose it with imported_name=None so rules can ignore it.
    source = "import pkg.other\n"
    imps = collect_imports(source, module="pkg.mod")
    assert len(imps) == 1
    assert imps[0].from_module == "pkg.other"
    assert imps[0].imported_name is None


def test_relative_import_is_resolved_against_current_module():
    source = "from .sibling import thing\n"
    imps = collect_imports(source, module="pkg.mod")
    assert len(imps) == 1
    assert imps[0].from_module == "pkg.sibling"
    assert imps[0].imported_name == "thing"


def test_relative_import_two_dots():
    source = "from ..other import x\n"
    imps = collect_imports(source, module="pkg.sub.mod")
    assert imps[0].from_module == "pkg.other"


def test_aliased_import_keeps_original_name():
    source = "from pkg.other import helper as h\n"
    imps = collect_imports(source, module="pkg.mod")
    assert imps[0].imported_name == "helper"
    assert imps[0].alias == "h"


def test_syntax_error_returns_empty():
    assert collect_imports("from x import (", module="m") == []


def test_star_import_is_collected_with_imported_name_star():
    source = "from pkg.other import *\n"
    imps = collect_imports(source, module="pkg.mod")
    assert len(imps) == 1
    assert imps[0].imported_name == "*"
    assert imps[0].from_module == "pkg.other"


def test_relative_import_beyond_package_depth_is_dropped():
    # `mod` is top-level (no dots); `from ...pkg import x` climbs further up
    # than there are segments, so it cannot be resolved and must be skipped
    # rather than raising or producing a bogus module name.
    source = "from ...pkg import x\n"
    assert collect_imports(source, module="mod") == []


def test_relative_import_with_no_target_and_no_remaining_package_is_dropped():
    # `from . import x` inside a top-level module has no parent package left
    # to resolve against.
    source = "from . import x\n"
    assert collect_imports(source, module="top") == []


def test_col_offset_points_at_imported_name_not_from_keyword():
    """Editors underline ``range start..end``; we want it on the symbol name."""
    source = "from pkg.other import helper\n"
    imps = collect_imports(source, module="pkg.mod")
    assert imps[0].col_offset == source.index("helper")


def test_col_offset_per_name_in_multi_import():
    source = "from pkg.other import helper, api\n"
    imps = collect_imports(source, module="pkg.mod")
    by_name = {i.imported_name: i.col_offset for i in imps}
    assert by_name["helper"] == source.index("helper")
    assert by_name["api"] == source.index("api")




def test_relative_import_inside_a_package_anchors_on_the_package():
    """``from .core import x`` in ``lib/__init__.py`` resolves to ``lib.core``."""
    refs = collect_imports("from .core import helper\n", module="lib", is_package=True)
    assert [(r.from_module, r.imported_name) for r in refs] == [("lib.core", "helper")]


def test_relative_import_inside_a_module_anchors_on_the_parent():
    refs = collect_imports("from .core import helper\n", module="lib.mod")
    assert [(r.from_module, r.imported_name) for r in refs] == [("lib.core", "helper")]


def test_bare_relative_import_inside_a_package_resolves_to_itself():
    refs = collect_imports("from . import core\n", module="lib", is_package=True)
    assert [(r.from_module, r.imported_name) for r in refs] == [("lib", "core")]


def test_parent_relative_import_inside_a_subpackage():
    refs = collect_imports("from ..globals import g\n", module="lib.json", is_package=True)
    assert [(r.from_module, r.imported_name) for r in refs] == [("lib.globals", "g")]
