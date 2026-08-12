"""Visibility markers and the ``@dynamic`` escape hatch.

These decorators are pure identities at runtime — they do not wrap, do not
add attributes, do not modify behaviour. All enforcement is static.
"""
from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import TypeVar, overload

_T = TypeVar("_T")


class Visibility(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"


def public(obj: _T) -> _T:
    """Mark a symbol as ``public`` (visible from anywhere)."""
    return obj


def internal(obj: _T) -> _T:
    """Mark a symbol as ``internal`` (visible inside its top-level package)."""
    return obj


def private(obj: _T) -> _T:
    """Mark a symbol as ``private`` (visible inside its defining module)."""
    return obj


@overload
def dynamic(obj: _T) -> _T: ...
@overload
def dynamic(*, reason: str) -> Callable[[_T], _T]: ...


def dynamic(obj: _T | None = None, *, reason: str | None = None):
    """Escape hatch: mark a function/class as relying on dynamic Python.

    Usable bare (``@dynamic``) or parameterised (``@dynamic(reason="...")``).
    """
    if obj is not None:
        return obj

    def _decorator(target: _T) -> _T:
        return target

    return _decorator


class Public:
    """Marker for ``Annotated[T, Public]`` visibility on module/class attributes.

    Decorators (``@public``) can't be applied to plain variable assignments,
    so annotated attributes use these marker classes as ``Annotated``
    metadata instead — the same static-only, zero-runtime-effect philosophy
    as ``typing.Final`` or PEP 702's ``@deprecated``.
    """


class Internal:
    """Marker for ``Annotated[T, Internal]`` visibility on module/class attributes."""


class Private:
    """Marker for ``Annotated[T, Private]`` visibility on module/class attributes."""


# ---------------------------------------------------------------------------
# Static-analysis helpers (not part of the user-facing runtime API).
# ---------------------------------------------------------------------------

# Mapping from the simple decorator tail-name to a visibility level. Includes
# both the lower-case decorator identities (``@internal``) and the PascalCase
# marker classes used inside ``typing.Annotated[T, Internal]`` for attributes
# that can't carry a decorator (module/class-level variables).
_VISIBILITY_BY_NAME = {
    "public": "public",
    "internal": "internal",
    "private": "private",
    "Public": "public",
    "Internal": "internal",
    "Private": "private",
}


def get_visibility_name(decorator_name: str) -> str | None:
    """Return the visibility level encoded by a decorator reference.

    Accepts both bare names (``"internal"``) and dotted references
    (``"scopify.internal"``, ``"markers.private"``). Returns ``None`` if the
    decorator is unrelated to visibility.
    """
    if not decorator_name:
        return None
    tail = decorator_name.rsplit(".", 1)[-1]
    return _VISIBILITY_BY_NAME.get(tail)

