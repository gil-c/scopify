"""Unit tests for SC003 (visibility annotation vs. underscore naming mismatch)."""
from __future__ import annotations

from pathlib import Path

from scopify.rules import naming


def _check(source: str, file: Path = Path("mod.py")):
    return naming.check(source, module="mod", file=file)


def test_public_on_underscore_name_is_an_error():
    diags = _check("from scopify import public\n\n@public\ndef _secret():\n    pass\n")
    assert len(diags) == 1
    d = diags[0]
    assert d.code == "SC003"
    assert d.severity == "error"
    assert d.symbol == "public"
    assert "_secret" in d.message
def test_internal_on_non_underscore_name_is_a_warning():
    diags = _check("from scopify import internal\n\n@internal\ndef helper():\n    pass\n")
    assert len(diags) == 1
    d = diags[0]
    assert d.severity == "warning"
    assert d.symbol == "internal"
def test_public_on_non_underscore_name_is_fine():
    assert _check("from scopify import public\n\n@public\ndef helper():\n    pass\n") == []
def test_internal_on_underscore_name_is_fine():
    assert _check("from scopify import internal\n\n@internal\ndef _helper():\n    pass\n") == []
def test_dunder_name_never_flagged():
    src = "from scopify import public\n\n@public\ndef __init__(self):\n    pass\n"
    assert _check(src) == []
def test_class_decorator_checked():
    diags = _check("from scopify import public\n\n@public\nclass _Widget:\n    pass\n")
    assert len(diags) == 1
def test_method_and_nested_class_checked():
    src = (
        "from scopify import internal\n\n"
        "class Outer:\n"
        "    @internal\n"
        "    def method(self):\n"
        "        pass\n\n"
        "    class Inner:\n"
        "        @internal\n"
        "        def deep(self):\n"
        "            pass\n"
    )
    diags = _check(src)
    assert {d.message.split("'")[1] for d in diags} == {"method", "deep"}
def test_annotated_metadata_public_mismatch():
    src = "from typing import Annotated\nfrom scopify import Public\n\n_x: Annotated[int, Public] = 1\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].symbol == "Public"
    assert diags[0].severity == "error"
def test_annotated_metadata_internal_mismatch_is_warning():
    src = "from typing import Annotated\nfrom scopify import Internal\n\nx: Annotated[int, Internal] = 1\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].severity == "warning"
def test_annotated_without_metadata_match_is_ignored():
    src = "from typing import Annotated\n\nx: Annotated[int, 'meta'] = 1\n"
    assert _check(src) == []
def test_non_annotated_subscript_annotation_is_ignored():
    assert _check("from typing import List\n\nx: List[int] = []\n") == []
def test_class_attribute_annotated_metadata_checked():
    src = (
        "from typing import Annotated\nfrom scopify import Public\n\n"
        "class Widget:\n"
        "    _flag: Annotated[bool, Public] = False\n"
    )
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].symbol == "Public"
def test_non_annotated_annassign_ignored():
    assert _check("x: int = 1\n") == []
def test_dotted_or_aliased_decorator_is_skipped():
    src = "import scopify\n\n@scopify.internal\ndef helper():\n    pass\n"
    assert _check(src) == []
def test_aliased_import_decorator_is_skipped():
    src = "from scopify import internal as hidden\n\n@hidden\ndef helper():\n    pass\n"
    assert _check(src) == []
def test_only_first_visibility_decorator_considered():
    src = (
        "from scopify import public, dynamic\n\n"
        "@dynamic\n@public\ndef _secret():\n    pass\n"
    )
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].symbol == "public"
def test_syntax_error_returns_no_diagnostics():
    assert _check("def broken(:\n") == []
def test_diagnostics_sorted_by_location():
    src = (
        "from scopify import public, internal\n\n"
        "@internal\ndef helper():\n    pass\n\n"
        "@public\ndef _secret():\n    pass\n"
    )
    diags = _check(src)
    assert [d.line for d in diags] == sorted(d.line for d in diags)
