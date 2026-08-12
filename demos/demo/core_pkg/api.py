"""Core package: the library's public surface plus its internal and private guts.

This single file anchors the two "static visibility" rules used throughout
the demo. Every other file either legally uses these symbols (same package /
same module) or illegally reaches across a boundary it shouldn't cross.
"""
from scopify import internal, private, public


@public
def stable_api(x: int) -> int:
    """@public — callable from any package. The only sanctioned entry point
    into this module from the outside world.
    """
    return _polish(x) + helper(x)


@internal  # scopify: ignore[SC003]
def helper(x: int) -> int:
    """@internal — callable from any module *inside* this top-level package
    (``core_pkg``), but Scopify raises **SC001** (see
    ``src/scopify/rules/access.py``) if a *different* top-level package
    imports it directly. See ``consumer_pkg/cross_package.py``.

    Named without a leading underscore on purpose, to also serve as the
    SC001 example above — that would normally trip **SC003** (naming vs.
    visibility mismatch, see ``core_pkg/naming_mismatches.py``), so it is
    silenced here with the generic inline suppression comment instead of
    renaming it and losing the SC001 example.
    """
    return x * 2


@private
def _polish(x: int) -> int:
    """@private — callable only from *this exact module*
    (``core_pkg/api.py``). Scopify raises **SC002** (see
    ``src/scopify/rules/private.py``) even for a sibling module in the same
    package: ``@private`` is module-scoped, not package-scoped.
    """
    return x + 1


@internal  # scopify: ignore[SC003]
class InternalRegistry:
    """@internal class — the same SC001 rule applies to classes as to
    functions: legal to use from ``core_pkg.sibling``, illegal from
    ``consumer_pkg``. Suppressed for SC003 for the same reason as
    ``helper`` above.
    """

    def __init__(self) -> None:
        self._items: list[int] = []

    def add(self, item: int) -> None:
        self._items.append(item)
