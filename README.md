# Scopify

Strict accessibility linter for Python: enforce `@public` / `@internal` / `@private`
declarations across a project, the way C#, Java, TypeScript or Rust do natively.

The core idea:

> Python has one word for "hidden" — the leading underscore — and it never
> says *hidden from whom*. Scopify adds the missing distinction between what
> your project uses internally and what your users are allowed to rely on,
> and enforces it statically.

## Quickstart

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e ".[dev,lsp]"
pytest
scopify check path/to/project
```

After cloning, enable the repository hooks once:

```bash
git config core.hooksPath .githooks
```

Every new worktree will then create its own `venv` in the background and
install Scopify with its development and LSP dependencies. Progress is written
to `.venv-setup.log`.

## Visibility markers

Three levels, three concentric rings around a symbol:

```python
from scopify import public, internal, private

@public
def api_function(): ...   # published API — my users may rely on it

@internal
def helper(): ...         # anywhere inside my own project, promised to nobody outside

@private
def _secret(): ...        # this module only
```

The middle level is the one Python cannot express. The underscore convention
says *hidden*, but never *hidden from whom* — so project-wide plumbing and
published API end up looking exactly alike. `@internal` is that missing word.

| Level | Who may use it | Typical example |
|---|---|---|
| `@private` | the defining module | a helper used two lines below |
| `@internal` | the whole project | machinery every module needs, promised to no one |
| `@public` | consumers of the library | what the README tells people to import |

The decorators are pure runtime identities. All enforcement is static, and
covers both `from X import Y` and later usage (`import pkg.mod` + qualified
access, `Class.member`/`instance.member`).

## The published API is read from your code

Scopify does not need you to annotate anything to tell an API surface from
project plumbing. A package already states its public surface in its
`__init__.py`, in one of the two universal conventions:

```python
# Either the explicit list...
__all__ = ["Client", "Response"]

# ...or the PEP 484 redundant alias, which type checkers already honour:
from .app import Flask as Flask
```

Scopify reads that declaration as a **door**: what goes through it is
`@public`, what does not is at most `@internal`. Two rules follow, and both
work on a codebase that has never seen a Scopify decorator:

* **SC004** — someone reached *past* the door, importing plumbing the package
  never promised. On `httpx` this immediately finds its own test suite doing
  `from httpx._urlparse import urlparse`.
* **SC005** — the door contradicts itself: it publishes a name that resolves
  to nothing (a latent `from pkg import *` crash), or a name declared
  `@internal` at its definition site.

A package that declares no door makes no promise, so nothing is enforced
against it.

## Configuration

`scopify.toml` (or `[tool.scopify]` in `pyproject.toml`):

```toml
default_visibility = "public"        # or "internal" for strict-by-default
roots = ["src.pkgA", "src.pkgB"]      # explicit project boundaries for @internal
disabled_rules = ["SC010"]            # rule codes to skip
```

`roots` declares where one project ends and the next begins — the boundary
`@internal` is scoped to. It fixes ambiguous layouts (e.g. `src/`) and
monorepos shipping several distributions, where the first dotted segment
alone can't tell them apart — see `modules.top_level_package`.

## Suppressing a single line

Any diagnostic (SC001/SC002, SC004/SC005, SC01x, SC003…) can be silenced
inline, without touching `disabled_rules`:

```python
from alpha.core import helper  # scopify: ignore[SC001]

@public
def _secret(): ...             # scopify: ignore  (silences every code on this line)
```

## SC003 — visibility vs. naming mismatch

Flags a decorator/annotation that disagrees with the leading-underscore
convention: `@public def _secret()` (error — the underscore says hidden,
the decorator says public) and `@internal def helper()` (warning — no
underscore, so it reads like public API). The LSP quick fix can flip the
decorator to match, or suppress the line.
