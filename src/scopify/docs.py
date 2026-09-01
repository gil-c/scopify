"""Per-rule documentation for all Scopify rules.

Each entry contains:
- code          : rule identifier (e.g. "SC001")
- title         : short human-readable name
- what          : one-line description of what is detected
- why           : rationale / why this matters
- example_bad   : offending code snippet
- example_good  : corrected version or escape hatch
- escape        : escape hatch syntax
- severity      : default severity level
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleDoc:
    code: str
    title: str
    what: str
    why: str
    example_bad: str
    example_good: str
    escape: str
    severity: str = "error"

    def render(self) -> str:
        """Return a human-readable multi-line description for terminal output."""
        lines = [
            f"{self.code}  {self.title}",
            f"{'─' * (len(self.code) + 2 + len(self.title))}",
            "",
            f"Severity : {self.severity}",
            "",
            "What     :",
            f"  {self.what}",
            "",
            "Why      :",
        ]
        for para in self.why.strip().splitlines():
            lines.append(f"  {para}" if para else "")
        lines += [
            "",
            "Example — violation:",
            *[f"  {ln}" for ln in self.example_bad.strip().splitlines()],
            "",
            "Example — fix / escape:",
            *[f"  {ln}" for ln in self.example_good.strip().splitlines()],
            "",
            "Escape hatch:",
            f"  {self.escape}",
            "",
        ]
        return "\n".join(lines)


_RULES: list[RuleDoc] = [
    # ------------------------------------------------------------------
    # Accessibility rules
    # ------------------------------------------------------------------
    RuleDoc(
        code="SC001",
        title="cross-project import of an @internal symbol",
        what=(
            "Importing a symbol marked @internal from outside the project that "
            "defines it."
        ),
        why=(
            "@internal means 'usable anywhere inside my own project, promised to "
            "nobody outside'. It is the level Python cannot express: the underscore "
            "convention only says 'hidden', never 'hidden from whom'. Importing an "
            "@internal symbol from another project creates coupling to something "
            "that carries no compatibility promise and will break on any refactor."
        ),
        example_bad="""\
# beta/user.py
from alpha.core import _helper   # @internal in alpha — violation

# alpha/core.py
from scopify import internal

@internal
def _helper(): ...
""",
        example_good="""\
# Option 1 — use a @public API surface instead:
# alpha/core.py
from scopify import public

@public
def helper(): ...

# beta/user.py
from alpha.core import helper   # OK

# Option 2 — suppress a single import with inline comment:
from alpha.core import _helper  # scopify: ignore[SC001]
""",
        escape="# scopify: ignore[SC001]  (trailing comment on the import line)",
        severity="error",
    ),
    RuleDoc(
        code="SC002",
        title="cross-module import of a @private symbol",
        what=(
            "Importing a symbol marked @private from any module other than its "
            "defining module."
        ),
        why=(
            "@private means 'visible only inside this module'. Unlike @internal "
            "(which spans the whole project), even a sibling module in the same "
            "package must not import it. Violations expose implementation details "
            "that have no stable contract."
        ),
        example_bad="""\
# alpha/utils.py
from alpha.core import _impl   # @private in alpha.core — violation

# alpha/core.py
from scopify import private

@private
def _impl(): ...
""",
        example_good="""\
# Promote to @internal if the sibling legitimately needs it:
from scopify import internal

@internal
def _impl(): ...

# Or suppress:
from alpha.core import _impl  # scopify: ignore[SC002]
""",
        escape="# scopify: ignore[SC002]  (trailing comment on the import line)",
        severity="error",
    ),
    RuleDoc(
        code="SC003",
        title="visibility annotation conflicts with naming convention",
        what=(
            "An explicit @public/@internal decorator disagrees with the leading-underscore "
            "naming convention."
        ),
        why=(
            "Python developers rely on the _underscore prefix as a 'non-public' signal "
            "long before annotations existed.  When decorator and name disagree it is "
            "almost always an oversight.\n"
            "\n"
            "Two sub-cases:\n"
            "  error   @public on an underscore-prefixed name (strong contradiction)\n"
            "  warning @internal on a non-underscore name (style nudge only)"
        ),
        example_bad="""\
from scopify import public, internal

@public          # ERROR: name says hidden, decorator says public
def _my_func(): ...

@internal        # WARNING: name reads like public API
def my_helper(): ...
""",
        example_good="""\
# Fix the name to match the intent:
@public
def my_func(): ...    # no underscore

@internal
def _my_helper(): ... # underscore matches internal

# Or suppress:
@public
def _my_func(): ...   # scopify: ignore[SC003]
""",
        escape="# scopify: ignore[SC003]  (trailing comment on the decorator line)",
        severity="error",  # sub-case for @public/_name; warning for the other sub-case
    ),
    RuleDoc(
        code="SC004",
        title="reaching past a package's published API",
        what=(
            "Importing, from outside a package, a name that the package does not "
            "publish in its __init__.py."
        ),
        why=(
            "A package states its public API in its __init__.py, either as "
            "`__all__ = [...]` or as the PEP 484 redundant alias "
            "(`from .app import Flask as Flask`). That declaration is the door: "
            "what goes through it is @public, what does not is at most @internal.\n"
            "\n"
            "Reaching around the door binds you to plumbing the authors never "
            "promised and are free to rename, move or delete in any release. This "
            "rule needs no annotation at all — it reads the door the project has "
            "already declared, so it works on any codebase from the first run.\n"
            "\n"
            "Silent when a package declares no door: no promise, nothing to enforce."
        ),
        example_bad="""\
# app/main.py
from lib.core import plumbing   # not published by 'lib' — violation

# lib/__init__.py
from .core import Client
__all__ = ["Client"]
""",
        example_good="""\
# Option 1 — go through the door:
from lib import Client

# Option 2 — publish it, if it really is API:
# lib/__init__.py
from .core import Client, plumbing
__all__ = ["Client", "plumbing"]

# Option 3 — suppress a deliberate reach:
from lib.core import plumbing  # scopify: ignore[SC004]
""",
        escape="# scopify: ignore[SC004]  (trailing comment on the import line)",
        severity="warning",
    ),
    RuleDoc(
        code="SC005",
        title="published API that contradicts itself",
        what=(
            "A name published by a package's __init__.py that does not resolve, or "
            "that is declared @internal/@private at its definition site."
        ),
        why=(
            "The door is written by hand and nothing checks it. Two failures follow.\n"
            "\n"
            "A published name that resolves to nothing is a latent crash: "
            "`from pkg import *` raises AttributeError.\n"
            "\n"
            "A published name declared @internal is a contradiction between what the "
            "project promises its users and what the author wrote at the definition "
            "site. One of the two is wrong, and only the author can say which.\n"
            "\n"
            "Only a *written* @internal counts: a visibility inherited from "
            "`default_visibility` is an assumption, not a statement."
        ),
        example_bad="""\
# lib/__init__.py
from .core import helper
__all__ = ["helper", "Ghost"]   # 'Ghost' resolves to nothing — violation

# lib/core.py
from scopify import internal

@internal                        # published, yet declared internal — violation
def helper(): ...
""",
        example_good="""\
# Fix the door:
__all__ = ["helper"]

# ...and settle the intent at the definition site:
from scopify import public

@public
def helper(): ...
""",
        escape="# scopify: ignore[SC005]  (trailing comment in the __init__.py)",
        severity="error",
    ),
    # ------------------------------------------------------------------
    # Dynamic construct rules
    # ------------------------------------------------------------------
    RuleDoc(
        code="SC010",
        title="dynamic attribute access via getattr/setattr/hasattr/delattr",
        what=(
            "A call to getattr/setattr/hasattr/delattr where the attribute name is not "
            "a string literal — scopify cannot statically resolve which symbol is accessed."
        ),
        why=(
            "Non-literal attribute names defeat all static visibility analysis. "
            "Scopify cannot know at analysis time which @internal or @private symbol "
            "the runtime will access, so the access escapes enforcement entirely."
        ),
        example_bad="""\
attr = "helper"
value = getattr(obj, attr)   # SC010: name is not a literal
""",
        example_good="""\
# Use a literal name:
value = getattr(obj, "helper")   # OK — literal, resolvable

# Or suppress if the dynamic access is intentional:
value = getattr(obj, attr)  # scopify: allow-dynamic

# Or annotate the function:
from scopify import dynamic

@dynamic(reason="plugin dispatch requires runtime attribute lookup")
def load_plugin(obj, name):
    return getattr(obj, name)
""",
        escape=(
            "# scopify: allow-dynamic          (inline, single line)\n"
            "  @dynamic(reason='...')           (function/class scope)\n"
            "  # scopify: dynamic-module       (whole file, near top)"
        ),
        severity="error",
    ),
    RuleDoc(
        code="SC011",
        title="use of eval / exec / compile",
        what="A call to eval(), exec(), or compile() with a dynamic string argument.",
        why=(
            "eval/exec/compile execute arbitrary code at runtime. Any symbol referenced "
            "inside the evaluated string is invisible to static analysis — visibility "
            "enforcement is completely bypassed for the executed code."
        ),
        example_bad="""\
eval("some_internal_func()")  # SC011
exec(user_code)               # SC011
""",
        example_good="""\
# Refactor to avoid dynamic execution, or suppress if unavoidable:
eval("some_internal_func()")  # scopify: allow-dynamic
""",
        escape=(
            "# scopify: allow-dynamic  |  @dynamic(reason='...')  |  # scopify: dynamic-module"
        ),
        severity="error",
    ),
    RuleDoc(
        code="SC012",
        title="dynamic import via importlib or __import__",
        what=(
            "A call to importlib.import_module() or __import__() with a non-literal "
            "module name."
        ),
        why=(
            "Dynamic imports load modules whose name is unknown at analysis time. "
            "Scopify cannot build the import graph for dynamically loaded modules, "
            "so @internal/@private constraints on their symbols go unenforced."
        ),
        example_bad="""\
import importlib
mod = importlib.import_module(plugin_name)  # SC012
""",
        example_good="""\
# Use a literal:
mod = importlib.import_module("mypackage.plugin")  # OK

# Or suppress:
mod = importlib.import_module(plugin_name)  # scopify: allow-dynamic
""",
        escape=(
            "# scopify: allow-dynamic  |  @dynamic(reason='...')  |  # scopify: dynamic-module"
        ),
        severity="error",
    ),
    RuleDoc(
        code="SC013",
        title="module-level __getattr__ or __getattribute__",
        what=(
            "A module defines __getattr__ or __getattribute__ at module scope, enabling "
            "dynamic attribute resolution for the module itself."
        ),
        why=(
            "Module-level __getattr__ (PEP 562) intercepts attribute lookups on the "
            "module object. Any symbol the function returns is invisible to static "
            "analysis — importers can access anything, bypassing @internal/@private."
        ),
        example_bad="""\
# mypackage/mod.py
def __getattr__(name):           # SC013
    return _registry[name]
""",
        example_good="""\
# Expose only what you intend explicitly; use a dispatch dict with @public:
_registry = {"helper": _helper}

def get(name: str):              # explicit, analysable
    return _registry[name]

# Or suppress if the lazy-loading pattern is intentional:
def __getattr__(name):  # scopify: allow-dynamic
    return _registry[name]
""",
        escape=(
            "# scopify: allow-dynamic  |  @dynamic(reason='...')  |  # scopify: dynamic-module"
        ),
        severity="error",
    ),
    RuleDoc(
        code="SC014",
        title="explicit custom metaclass",
        what="A class declares an explicit metaclass= argument (other than type).",
        why=(
            "Custom metaclasses can redefine attribute creation, __getattr__, and "
            "class construction at runtime. They make static analysis of the class' "
            "members unreliable — added or transformed attributes are invisible."
        ),
        example_bad="""\
class MyMeta(type):
    def __new__(mcs, name, bases, ns): ...

class MyClass(metaclass=MyMeta):  # SC014
    pass
""",
        example_good="""\
# Prefer __init_subclass__, __class_getitem__, or descriptors for most needs.

# Or suppress if the metaclass is unavoidable (e.g. ABCMeta):
class MyABC(metaclass=ABCMeta):  # scopify: allow-dynamic
    pass
""",
        escape=(
            "# scopify: allow-dynamic  |  @dynamic(reason='...')  |  # scopify: dynamic-module"
        ),
        severity="error",
    ),
    RuleDoc(
        code="SC015",
        title="direct __dict__ mutation",
        what=(
            "A call that mutates an object's __dict__ directly "
            "(e.g. obj.__dict__['key'] = val, obj.__dict__.update(...))."
        ),
        why=(
            "__dict__ mutation bypasses the normal attribute-setting protocol and is "
            "invisible to static analysis. It can add or overwrite any symbol, including "
            "@private ones, without any visibility check."
        ),
        example_bad="""\
obj.__dict__["_secret"] = value   # SC015
obj.__dict__.update(kwargs)       # SC015
""",
        example_good="""\
# Use normal assignment; if the attribute is dynamic use setattr with a literal:
obj._secret = value               # analysable
setattr(obj, "_secret", value)    # OK — literal name

# Or suppress:
obj.__dict__["_secret"] = value   # scopify: allow-dynamic
""",
        escape=(
            "# scopify: allow-dynamic  |  @dynamic(reason='...')  |  # scopify: dynamic-module"
        ),
        severity="error",
    ),
    RuleDoc(
        code="SC016",
        title="frame introspection",
        what=(
            "A call to inspect.currentframe(), inspect.stack(), inspect.trace(), or "
            "sys._getframe()."
        ),
        why=(
            "Frame introspection reads the call stack at runtime and can access local "
            "variables, globals, and closures of any caller — including @private symbols. "
            "It also makes code fragile to inlining, tail-call optimisation, and other "
            "future Python optimisations."
        ),
        example_bad="""\
import inspect
frame = inspect.currentframe()   # SC016
caller_locals = frame.f_locals
""",
        example_good="""\
# Pass needed values explicitly instead of reading the caller's frame.

# Or suppress:
frame = inspect.currentframe()  # scopify: allow-dynamic
""",
        escape=(
            "# scopify: allow-dynamic  |  @dynamic(reason='...')  |  # scopify: dynamic-module"
        ),
        severity="error",
    ),
    RuleDoc(
        code="SC017",
        title="monkey-patching an attribute of an imported name",
        what=(
            "Assigning to an attribute of a name that was imported from another module "
            "(e.g. other_module.func = replacement)."
        ),
        why=(
            "Monkey-patching modifies a symbol in another module after import. "
            "It is invisible to static analysis — any code that later uses "
            "other_module.func will execute the patched version without the patching "
            "being visible at the call site. It also bypasses @private/@internal "
            "constraints."
        ),
        example_bad="""\
import alpha.core
alpha.core.helper = lambda: None  # SC017 — monkey-patching
""",
        example_good="""\
# Prefer dependency injection or adapter patterns instead of patching.
# In tests, use pytest monkeypatch or unittest.mock.patch:
def test_something(monkeypatch):
    monkeypatch.setattr(alpha.core, "helper", lambda: None)  # scopify: allow-dynamic
""",
        escape=(
            "# scopify: allow-dynamic  |  @dynamic(reason='...')  |  # scopify: dynamic-module"
        ),
        severity="warning",
    ),
    RuleDoc(
        code="SC018",
        title="write via globals() / locals() / vars()",
        what=(
            "A call to globals(), locals(), or vars() whose return value is used for a "
            "write operation (e.g. globals()['x'] = val, globals().update(...))."
        ),
        why=(
            "Writing through the globals/locals/vars namespace bypasses normal assignment "
            "and is invisible to static analysis. It can silently create or overwrite "
            "any name, including @private ones."
        ),
        example_bad="""\
globals()["_secret"] = value      # SC018
globals().update({"key": val})    # SC018
""",
        example_good="""\
# Use normal assignment:
_secret = value                   # analysable

# Or suppress:
globals()["_secret"] = value      # scopify: allow-dynamic
""",
        escape=(
            "# scopify: allow-dynamic  |  @dynamic(reason='...')  |  # scopify: dynamic-module"
        ),
        severity="error",
    ),
    RuleDoc(
        code="SC020",
        title="package belongs to no declared zone",
        what=(
            "A package holds modules that no zone in [tool.scopify.zones] claims. "
            "Reported once per package, on its __init__.py. Silent unless the "
            "project declares at least one zone."
        ),
        why=(
            "A zone only means something if every module falls in exactly one. A "
            "package nobody claimed is outside the architecture: no rule protects "
            "it, and nothing stops the rest of the project reaching into it. One "
            "error per package, so adding a folder dirties one line, not the repo."
        ),
        example_bad="""\
# pyproject.toml declares zones, but not this one:
# scrapy/downloadermiddlewares/__init__.py:1: SC020
""",
        example_good="""\
[tool.scopify.zones.downloadermiddlewares]
modules = ["scrapy.downloadermiddlewares", "scrapy.downloadermiddlewares.**"]
exposes = ["RetryMiddleware"]
""",
        escape="# scopify: ignore[SC020]  |  run 'scopify zones --init'",
        severity="error",
    ),
    RuleDoc(
        code="SC021",
        title="declared zone matches no module",
        what=(
            "A zone declared in [tool.scopify.zones] whose 'modules' patterns match "
            "nothing in the project. Reported on pyproject.toml."
        ),
        why=(
            "A zone that matches nothing enforces nothing, silently. It is almost "
            "always a package that got renamed or deleted without the declaration "
            "following, and it leaves a hole nobody notices."
        ),
        example_bad="""\
[tool.scopify.zones.legacy]
modules = ["app.legacy.**"]   # app/legacy/ no longer exists -> SC021
""",
        example_good="""\
# Delete the zone, or point it at the package that replaced it:
[tool.scopify.zones.storage]
modules = ["app.storage.**"]
""",
        escape="# scopify: ignore[SC021]",
        severity="warning",
    ),
]

# Index by code for O(1) lookup.
_BY_CODE: dict[str, RuleDoc] = {r.code: r for r in _RULES}

ALL_RULES: list[RuleDoc] = _RULES


def get_rule(code: str) -> RuleDoc | None:
    """Return the :class:`RuleDoc` for *code*, or ``None`` if not found."""
    return _BY_CODE.get(code.upper())


def list_rules() -> list[RuleDoc]:
    """Return all rule docs, ordered by code."""
    return list(_RULES)
