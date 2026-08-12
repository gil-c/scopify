"""**SC003** — explicit visibility annotation vs. leading-underscore naming.

Long before ``@public``/``@internal`` existed, a leading underscore already
meant "not part of the public API". When both signals are present and
disagree, Scopify flags it — see ``src/scopify/rules/naming.py``.
"""
from typing import Annotated

from scopify import internal, public
from scopify.markers import Internal, Public


@public
def _looks_hidden_but_is_public():
    """SC003 (error): the underscore says "hidden", @public says the
    opposite — the contradiction most likely to leak something by
    accident.
    """


@internal
def looks_public_but_is_internal():
    """SC003 (warning): no leading underscore, so this reads like public
    API even though @internal restricts it to this package. Softer than
    the error above, since @internal is allowed to override naming
    convention on purpose.
    """


@internal  # scopify: ignore[SC003]
def deliberately_unprefixed():
    """Same shape as ``looks_public_but_is_internal`` above, but here the
    mismatch is intentional and silenced with the generic inline
    suppression comment instead of renaming the function.
    """


# SC003 (error) via `Annotated[T, Public]` metadata instead of a decorator —
# the same check applies to module/class attributes, which can't carry a
# decorator.
_hidden_constant: Annotated[int, Public] = 1

# SC003 (warning) via `Annotated[T, Internal]` metadata: no leading
# underscore on a symbol restricted to this package.
shared_constant: Annotated[int, Internal] = 2
