"""Visibility markers must be runtime identities with no side effects."""
from scopify import Visibility, dynamic, internal, private, public
from scopify.markers import get_visibility_name


def test_public_is_identity():
    def f():
        return 42

    assert public(f) is f
    assert f() == 42


def test_internal_and_private_are_identities():
    class C:
        pass

    assert internal(C) is C
    assert private(C) is C


def test_dynamic_is_identity_with_or_without_args():
    def f():
        return "ok"

    assert dynamic(f) is f

    decorator = dynamic(reason="serialization")
    assert callable(decorator)
    assert decorator(f) is f


def test_visibility_enum_has_three_levels():
    assert {v.value for v in Visibility} == {"public", "internal", "private"}


def test_get_visibility_name_recognises_decorators():
    assert get_visibility_name("public") == "public"
    assert get_visibility_name("scopify.public") == "public"
    assert get_visibility_name("internal") == "internal"
    assert get_visibility_name("markers.private") == "private"
    assert get_visibility_name("unrelated") is None

