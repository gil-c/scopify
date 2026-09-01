"""Visibility markers and the ``@dynamic`` escape hatch.

Three levels, three concentric rings around a symbol:

* ``@private``  — this module only.
* ``@internal`` — anywhere inside my own project, promised to nobody outside.
* ``@public``   — part of the published API: my users may rely on it.

The middle level is the one Python cannot express. The underscore convention
says "hidden" but never "hidden from whom", so project-wide plumbing and
published API end up looking alike. ``@internal`` is that missing word, and
the published API is read from the package's door (see ``scopify.exports``).

These decorators are pure identities at runtime — they do not wrap, do not
add attributes, do not modify behaviour. All enforcement is static.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import Enum
from typing import TypeVar, overload

_T = TypeVar("_T")


class Visibility(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"


def public(obj: _T) -> _T:
    """Mark a symbol as ``public`` — part of the API published to consumers."""
    return obj


#: ``including="*"`` — shared with every zone in the project, published to nobody
#: outside it. Spelled as a star rather than a keyword so it reads like the
#: glob it behaves as.
EVERY_ZONE = "*"


@overload
def internal(obj: _T) -> _T: ...
@overload
def internal(*, including: str | Sequence[str]) -> Callable[[_T], _T]: ...


def internal(obj: _T | None = None, *, including: str | Sequence[str] | None = None):
    """Mark a symbol as ``internal`` — usable inside its own zone.

    Bare, it stops at the zone that defines it. ``including=`` widens that
    by naming the zones let in, or ``including="*"`` for the whole project:

    - ``@internal`` — my zone
    - ``@internal(including="scrapy.http")`` — my zone, plus that one
    - ``@internal(including=["a", "b"])`` — my zone, plus those two
    - ``@internal(including="*")`` — every zone, nothing outside the project

    ``including=`` names *zones*, never modules. A module name would tie the
    declaration to a file that may move; a zone is the unit that is meant
    to outlive the layout.
    """
    if obj is not None:
        return obj

    def _decorator(target: _T) -> _T:
        return target

    return _decorator


def private(obj: _T) -> _T:
    """Mark a symbol as ``private`` — usable inside its defining module only."""
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
    """Marker for ``Annotated[T, Internal]`` visibility on module/class attributes.

    Subscript it to widen the scope, mirroring the decorator:
    ``Annotated[T, Internal["scrapy.http"]]`` or ``Annotated[T, Internal["*"]]``.
    """

    def __class_getitem__(cls, item: object) -> type[Internal]:
        return cls


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

