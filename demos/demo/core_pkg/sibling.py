"""Same-package consumer of ``core_pkg.api`` — the "clean" side of SC001.

Importing ``@internal`` symbols here is LEGAL: ``sibling`` and ``api`` both
live in the top-level package ``core_pkg``, and SC001 only fires across
*package* boundaries (``src/scopify/rules/access.py``, line: the
``top_level_package(imp.importer) == top_level_package(imp.from_module)``
early-continue).

Note we do NOT import ``_polish`` here even though we're in the same
package: ``@private`` is scoped to its *defining module*, not its package,
so that import would still trip SC002. See ``consumer_pkg/cross_package.py``
for that violation instead.
"""
from core_pkg.api import InternalRegistry, helper, stable_api


def run(x: int) -> int:
    registry = InternalRegistry()
    registry.add(helper(x))
    return stable_api(x)
