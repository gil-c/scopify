"""Tests for the PA01x dynamic-construct rules (scopify.rules.dynamic)."""
from __future__ import annotations

from pathlib import Path

from scopify.rules import dynamic as dynamic_rule

FILE = Path("mod.py")


def _codes(source: str) -> list[str]:
    return [d.code for d in dynamic_rule.check(source, module="mod", file=FILE)]


# --- SC010: getattr/setattr/hasattr/delattr with a non-literal name --------


def test_getattr_with_variable_name_is_flagged():
    src = "attr = 'x'\ngetattr(obj, attr)\n"
    assert _codes(src) == ["SC010"]


def test_getattr_with_literal_name_is_allowed():
    src = "getattr(obj, 'x')\n"
    assert _codes(src) == []


def test_setattr_with_variable_name_is_flagged():
    src = "name = 'x'\nsetattr(obj, name, 1)\n"
    assert _codes(src) == ["SC010"]


def test_hasattr_and_delattr_with_variable_name_are_flagged():
    src = "n = 'x'\nhasattr(obj, n)\ndelattr(obj, n)\n"
    assert _codes(src) == ["SC010", "SC010"]


def test_getattr_with_too_few_args_is_ignored():
    # Malformed call — not our job to enforce arity, just don't crash.
    assert _codes("getattr(obj)\n") == []


# --- SC011: eval / exec / compile ------------------------------------------


def test_eval_is_flagged():
    assert _codes("eval('1 + 1')\n") == ["SC011"]


def test_exec_is_flagged():
    assert _codes("exec('x = 1')\n") == ["SC011"]


def test_compile_is_flagged():
    assert _codes("compile('x = 1', '<string>', 'exec')\n") == ["SC011"]


# --- SC012: importlib.import_module / __import__ ----------------------------


def test_import_module_with_variable_is_flagged():
    src = "import importlib\nname = 'os'\nimportlib.import_module(name)\n"
    assert _codes(src) == ["SC012"]


def test_import_module_with_literal_is_allowed():
    src = "import importlib\nimportlib.import_module('os')\n"
    assert _codes(src) == []


def test_dunder_import_with_variable_is_flagged():
    src = "name = 'os'\n__import__(name)\n"
    assert _codes(src) == ["SC012"]


def test_dunder_import_with_literal_is_allowed():
    assert _codes("__import__('os')\n") == []


# --- SC013: module-level __getattr__ / __getattribute__ --------------------


def test_module_level_getattr_is_flagged():
    assert _codes("def __getattr__(name):\n    pass\n") == ["SC013"]


def test_module_level_getattribute_is_flagged():
    assert _codes("def __getattribute__(name):\n    pass\n") == ["SC013"]


def test_class_level_getattr_is_not_flagged_by_pa013():
    # __getattr__ on a class is normal dunder-based attribute access override,
    # distinct from the module-level hook this rule targets.
    src = "class Foo:\n    def __getattr__(self, name):\n        pass\n"
    assert _codes(src) == []


# --- SC014: explicit custom metaclass ---------------------------------------


def test_explicit_metaclass_is_flagged():
    src = "class Foo(metaclass=Meta):\n    pass\n"
    diags = dynamic_rule.check(src, module="mod", file=FILE)
    assert [d.code for d in diags] == ["SC014"]
    assert diags[0].severity == "warning"


def test_class_without_metaclass_is_not_flagged():
    assert _codes("class Foo:\n    pass\n") == []


# --- Escape hatches ----------------------------------------------------------


def test_inline_allow_dynamic_comment_suppresses_diagnostic():
    src = "attr = 'x'\ngetattr(obj, attr)  # scopify: allow-dynamic\n"
    assert _codes(src) == []


def test_dynamic_decorator_suppresses_diagnostics_in_function_body():
    src = (
        "from scopify import dynamic\n"
        "\n"
        "@dynamic(reason='needed')\n"
        "def helper():\n"
        "    attr = 'x'\n"
        "    return getattr(obj, attr)\n"
    )
    assert _codes(src) == []


def test_dynamic_decorator_does_not_suppress_diagnostics_outside_its_body():
    src = (
        "from scopify import dynamic\n"
        "\n"
        "@dynamic\n"
        "def helper():\n"
        "    pass\n"
        "\n"
        "attr = 'x'\n"
        "getattr(obj, attr)\n"
    )
    assert _codes(src) == ["SC010"]


def test_dynamic_decorator_alias_is_recognised():
    src = (
        "from scopify import dynamic as unsafe\n"
        "\n"
        "@unsafe(reason='needed')\n"
        "def helper():\n"
        "    attr = 'x'\n"
        "    return getattr(obj, attr)\n"
    )
    assert _codes(src) == []


def test_dynamic_class_decorator_suppresses_diagnostics_in_class_body():
    src = (
        "from scopify import dynamic\n"
        "\n"
        "@dynamic\n"
        "class Foo:\n"
        "    attr = 'x'\n"
        "    getattr(object(), attr)\n"
    )
    assert _codes(src) == []


def test_module_marker_suppresses_all_diagnostics_in_file():
    src = (
        "# scopify: dynamic-module\n"
        "attr = 'x'\n"
        "getattr(obj, attr)\n"
        "eval('1')\n"
    )
    assert _codes(src) == []


def test_syntax_error_yields_no_diagnostics_but_does_not_raise():
    assert _codes("def broken(:\n") == []


# --- SC015: direct __dict__ manipulation ------------------------------------


def test_dict_subscript_assignment_is_flagged():
    assert _codes("obj.__dict__['x'] = 1\n") == ["SC015"]


def test_dict_whole_reassignment_is_flagged():
    assert _codes("obj.__dict__ = {}\n") == ["SC015"]


def test_dict_update_call_is_flagged():
    assert _codes("obj.__dict__.update({'x': 1})\n") == ["SC015"]


def test_dict_pop_call_is_flagged():
    assert _codes("obj.__dict__.pop('x')\n") == ["SC015"]


def test_plain_attribute_assignment_is_not_flagged_as_dict_manipulation():
    assert _codes("obj.x = 1\n") == []


def test_dict_read_access_is_not_flagged():
    assert _codes("x = obj.__dict__\n") == []


def test_dict_get_is_not_flagged():
    # Read-only helper method — not a mutator.
    assert _codes("x = obj.__dict__.get('a')\n") == []


# --- SC016: frame introspection ----------------------------------------------


def test_inspect_currentframe_is_flagged():
    assert _codes("import inspect\ninspect.currentframe()\n") == ["SC016"]


def test_inspect_stack_is_flagged():
    assert _codes("import inspect\ninspect.stack()\n") == ["SC016"]


def test_sys_getframe_is_flagged():
    assert _codes("import sys\nsys._getframe()\n") == ["SC016"]


def test_aliased_inspect_import_is_recognised():
    assert _codes("import inspect as insp\ninsp.currentframe()\n") == ["SC016"]


def test_from_import_currentframe_is_recognised():
    assert _codes("from inspect import currentframe\ncurrentframe()\n") == ["SC016"]


def test_unrelated_currentframe_call_is_not_flagged():
    # Some other object happening to expose a same-named method is fine —
    # only calls resolved back to the real ``inspect``/``sys`` modules count.
    assert _codes("obj.currentframe()\n") == []


# --- SC017: monkey-patching ---------------------------------------------------


def test_assigning_attribute_of_imported_module_is_flagged():
    assert _codes("import os\nos.path = None\n") == ["SC017"]


def test_assigning_attribute_of_from_imported_name_is_flagged():
    assert _codes("from mypkg import Service\nService.run = lambda self: None\n") == ["SC017"]


def test_self_attribute_assignment_is_not_flagged():
    src = "class Foo:\n    def __init__(self):\n        self.x = 1\n"
    assert _codes(src) == []


def test_cls_attribute_assignment_is_not_flagged():
    src = "class Foo:\n    @classmethod\n    def configure(cls):\n        cls.x = 1\n"
    assert _codes(src) == []


def test_local_variable_attribute_assignment_is_not_flagged():
    src = "obj = make_thing()\nobj.x = 1\n"
    assert _codes(src) == []


# --- SC018: globals()/locals()/vars() write access --------------------------


def test_globals_subscript_assignment_is_flagged():
    assert _codes("globals()['x'] = 1\n") == ["SC018"]


def test_locals_subscript_assignment_is_flagged():
    assert _codes("locals()['x'] = 1\n") == ["SC018"]


def test_vars_subscript_assignment_is_flagged():
    assert _codes("vars()['x'] = 1\n") == ["SC018"]


def test_globals_subscript_delete_is_flagged():
    assert _codes("del globals()['x']\n") == ["SC018"]


def test_globals_update_call_is_flagged():
    assert _codes("globals().update({'x': 1})\n") == ["SC018"]


def test_globals_pop_call_is_flagged():
    assert _codes("globals().pop('x')\n") == ["SC018"]


def test_globals_read_access_is_not_flagged():
    assert _codes("x = globals()['x']\n") == []
    assert _codes("x = globals().get('x')\n") == []
    assert _codes("print(globals())\n") == []


def test_vars_of_object_read_access_is_not_flagged():
    # `vars(obj)` (reading another object's namespace) is a read, not a write.
    assert _codes("x = vars(obj)\n") == []


def test_globals_write_suppressed_by_inline_marker():
    assert _codes("globals()['x'] = 1  # scopify: allow-dynamic\n") == []


# --- Escape hatches also cover the new rules ---------------------------------


def test_inline_marker_suppresses_dict_mutation():
    assert _codes("obj.__dict__['x'] = 1  # scopify: allow-dynamic\n") == []


def test_module_marker_suppresses_monkeypatch_and_frame_introspection():
    src = (
        "# scopify: dynamic-module\n"
        "import os\n"
        "import inspect\n"
        "os.path = None\n"
        "inspect.currentframe()\n"
    )
    assert _codes(src) == []
