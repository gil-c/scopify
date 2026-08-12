"""Symbol extraction with visibility from decorators."""
from scopify.markers import Visibility
from scopify.symbols import collect_symbols


def test_collects_function_with_internal_decorator():
    source = """
from scopify import internal, public

@internal
def helper():
    pass

@public
def api():
    pass

def undecorated():
    pass
"""
    syms = {s.name: s for s in collect_symbols(source, module="pkg.mod")}
    assert syms["helper"].visibility is Visibility.INTERNAL
    assert syms["api"].visibility is Visibility.PUBLIC
    assert syms["undecorated"].visibility is None  # default policy applied later
    assert syms["helper"].module == "pkg.mod"
    assert syms["helper"].lineno >= 1


def test_collects_class_and_methods():
    source = """
from scopify import internal, private

@internal
class C:
    @private
    def secret(self): ...
    def normal(self): ...
"""
    syms = list(collect_symbols(source, module="pkg.mod"))
    by_qual = {s.qualname: s for s in syms}
    assert by_qual["C"].visibility is Visibility.INTERNAL
    assert by_qual["C"].kind == "class"
    assert by_qual["C.secret"].visibility is Visibility.PRIVATE
    assert by_qual["C.secret"].kind == "method"
    assert by_qual["C.normal"].visibility is None


def test_aliased_decorator_import_is_recognised():
    source = """
from scopify import internal as _hidden

@_hidden
def helper(): ...
"""
    syms = {s.name: s for s in collect_symbols(source, module="pkg.mod")}
    assert syms["helper"].visibility is Visibility.INTERNAL


def test_syntax_error_yields_no_symbols_but_does_not_raise():
    source = "def broken(:\n"
    assert list(collect_symbols(source, module="pkg.mod")) == []


# --- Annotated[T, Marker] attributes (Phase 3) --------------------------------


def test_module_level_annotated_internal_attribute_is_collected():
    source = """
from typing import Annotated
from scopify import Internal

CONFIG: Annotated[dict, Internal] = {}
"""
    syms = {s.name: s for s in collect_symbols(source, module="pkg.mod")}
    assert syms["CONFIG"].visibility is Visibility.INTERNAL
    assert syms["CONFIG"].kind == "attribute"
    assert syms["CONFIG"].qualname == "CONFIG"


def test_module_level_annotated_public_and_private_attributes():
    source = """
from typing import Annotated
from scopify import Public, Private

API_VERSION: Annotated[str, Public] = "1.0"
_secret_key: Annotated[str, Private] = "shh"
"""
    syms = {s.name: s for s in collect_symbols(source, module="pkg.mod")}
    assert syms["API_VERSION"].visibility is Visibility.PUBLIC
    assert syms["_secret_key"].visibility is Visibility.PRIVATE


def test_annotated_without_visibility_marker_is_none():
    source = """
from typing import Annotated

COUNT: Annotated[int, "some other metadata"] = 0
"""
    syms = {s.name: s for s in collect_symbols(source, module="pkg.mod")}
    assert syms["COUNT"].visibility is None


def test_plain_annotation_without_annotated_wrapper_is_none():
    source = "COUNT: int = 0\n"
    syms = {s.name: s for s in collect_symbols(source, module="pkg.mod")}
    assert syms["COUNT"].visibility is None
    assert syms["COUNT"].kind == "attribute"


def test_class_level_annotated_attribute_is_collected_with_dotted_qualname():
    source = """
from typing import Annotated
from scopify import Internal

class Config:
    secret: Annotated[str, Internal] = ""
"""
    syms = {s.qualname: s for s in collect_symbols(source, module="pkg.mod")}
    assert syms["Config.secret"].visibility is Visibility.INTERNAL
    assert syms["Config.secret"].kind == "attribute"


def test_aliased_annotated_marker_import_is_recognised():
    source = """
from typing import Annotated
from scopify import Internal as Hidden

TOKEN: Annotated[str, Hidden] = ""
"""
    syms = {s.name: s for s in collect_symbols(source, module="pkg.mod")}
    assert syms["TOKEN"].visibility is Visibility.INTERNAL


def test_dotted_annotated_reference_is_recognised():
    source = """
import typing
import scopify

TOKEN: typing.Annotated[str, scopify.Internal] = ""
"""
    syms = {s.name: s for s in collect_symbols(source, module="pkg.mod")}
    assert syms["TOKEN"].visibility is Visibility.INTERNAL

