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

## `scopify zones` — where the layers are, and what breaks them

`@internal` only pays off once a codebase is split into parts that each
declare what they expose. `scopify zones` reads the import graph and shows
the split your code already has:

```console
$ scopify zones src/flask
scopify: 22 zone(s) over 7 layer(s) in 24 module(s).

  layer  6  flask (door)
  layer  5  flask.app, flask.blueprints
  layer  4  flask.sansio.app, flask.sansio.blueprints
  layer  3  flask.__main__, flask.sansio.scaffold, flask.testing
  layer  2  flask.cli, flask.sessions, flask.templating, flask.wrappers
  layer  1  flask.ctx, flask.debughelpers, flask.helpers, flask.json, flask.views
  layer  0  flask.config, flask.globals, flask.signals, flask.typing

  1 dependency knot(s), 4 import(s) to look at.

  ! 10 zones depend on each other in a circle: flask.app, flask.blueprints, ...
      flask.cli -> flask.app  (2 import(s))
        flask/cli.py:45   Flask      [import inside a function]
        flask/cli.py:124  Flask      [import inside a function]
      flask.debughelpers -> flask.blueprints  (1 import(s))
        flask/debughelpers.py:8   Blueprint  [runtime coupling]
```

Imports are grouped by the pair of zones they tie together, because that is
the unit of work: one cause, one file to move — not twenty red lines. Each
one is labelled with what it costs you:

- `runtime coupling` — a real dependency at import time.
- `annotation only` — used in type positions only; moving it under
  `if TYPE_CHECKING:` removes the edge.
- `import inside a function` — someone already worked around the cycle by
  hand. On werkzeug, 8 of the 13 reported imports are of this kind.
- `package door re-export` — a package importing its own submodules from
  its `__init__.py`. A facade cannot be written without them, so they are
  listed last.

Modules named in a declared list (`PLUGINS = ["app.plugin"]`) are treated as
dependencies *of* the registry, and the plugins importing it back are not
reported — otherwise every plugin system reads as a cycle.

Options: `--root PKG` (repeatable) narrows the analysis to some top-level
packages, e.g. to leave `tests/` out; `--format json` for machine output;
`--no-layers` prints only the knots.

**This is a diagnostic, not a gate. It always exits 0.** Removing a module
that half the project imports does shift which imports get reported, so
failing a build on it would blame whoever happened to touch the crossroads.

## What a zone hands out, and declaring it

Knowing where the layers are is half the story. The other half is what each
zone *exposes* — the symbols other zones import from it. That is the number
that says whether a zone is an interface or a drawer:

```
$ scopify zones src/werkzeug --coupling
scopify: 35 of 38 zone(s) hand out 170 symbol(s) to the rest of the project.

  werkzeug.datastructures  (1 module(s), exposes 25)
      Headers  used by 8 zone(s)  [werkzeug.datastructures]
      MultiDict  used by 5 zone(s)  [werkzeug.datastructures]
      ... and 19 more
      ! 25 symbols is not an interface, it is a drawer. Split this zone,
        or accept that the rest of the project depends on all of it.
```

The surface is read from **static imports only**, so it is a lower bound:
anything reached dynamically is invisible, and a symbol meant to be shared
but not used yet does not appear.

### Declaring zones yourself

Zones are guessed by default. Guessing is fine for a report and wrong for a
rule, so you can write them down. Scopify proposes, you name:

```toml
[tool.scopify.zones.http]
modules = ["scrapy.http", "scrapy.http.**"]
exposes = ["Request", "Response", "FormRequest"]
```

`modules` are dotted globs — `*` matches one segment, `**` any depth; the
most precise pattern wins when two zones overlap. The zone name is the table
key, chosen by a human, because scopify does not get to name your
architecture.

`scopify zones --init` prints the whole declaration, deduced from the imports
your project already makes, so pasting it changes nothing on day one.
`--write` appends it to `pyproject.toml` (appends, never rewrites — your
comments stay).

### SC020 / SC021 — keeping the declaration honest

Once — and **only** once — `[tool.scopify.zones]` exists, two rules wake up:

- **SC020**: a package no declared zone claims, reported once on its
  `__init__.py`. Adding a folder dirties one line, the folder you added,
  never the project. The fix is `scopify zones --declare <package>`, which
  prints the block to paste; in an editor the quick fix writes it into
  `pyproject.toml` for you.
- **SC021**: a declared zone whose patterns match nothing — usually a rename
  nobody propagated. Reported on `pyproject.toml`.

Declare nothing and both stay silent: existing projects see no change.

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
