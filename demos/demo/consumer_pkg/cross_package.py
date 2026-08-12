"""Cross-package consumer — deliberately illegal on two counts at once.

Open this file (or run ``scopify check demos/demo``) to see both
foundational visibility rules fire side by side:

* **SC001** — cross-package import of an ``@internal`` symbol
  (``src/scopify/rules/access.py``).
* **SC002** — cross-module import of a ``@private`` symbol
  (``src/scopify/rules/private.py``). Private is stricter than internal:
  it fires even though ``_polish`` and this file are unrelated packages,
  same as it would if they were siblings in the same package.
"""
from core_pkg.api import InternalRegistry  # SC001 -- @internal class imported across packages
from core_pkg.api import helper  # SC001 -- @internal function imported across packages
from core_pkg.api import _polish  # SC002 -- @private symbol imported from another module
from core_pkg.api import stable_api  # OK -- @public, no diagnostic


def use(x: int) -> int:
    registry = InternalRegistry()
    registry.add(helper(x))
    return stable_api(x) + _polish(x)
