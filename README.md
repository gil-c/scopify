# PyAccess

Strict accessibility linter for Python: enforce `@public` / `@internal` / `@private`
declarations across a project, the way C#, Java, TypeScript or Rust do natively.

This repository currently hosts a Phase 1 POC that demonstrates the core idea:

> Detect a cross-package import of a symbol marked `@internal`.

## Quickstart

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e ".[dev,lsp]"
pytest
pyaccess check path/to/project
```

After cloning, enable the repository hooks once:

```bash
git config core.hooksPath .githooks
```

Every new worktree will then create its own `venv` in the background and
install PyAccess with its development and LSP dependencies. Progress is written
to `.venv-setup.log`.

## Visibility markers

```python
from pyaccess import public, internal, private

@public
def api_function(): ...

@internal
def helper(): ...     # only callable from within the same package

@private
def _secret(): ...    # only callable from within the same module
```

The decorators are pure runtime identities. All enforcement is static, and
covers both `from X import Y` and later usage (`import pkg.mod` + qualified
access, `Class.member`/`instance.member`).

## Configuration

`pyaccess.toml` (or `[tool.pyaccess]` in `pyproject.toml`):

```toml
default_visibility = "public"        # or "internal" for strict-by-default
roots = ["src.pkgA", "src.pkgB"]      # explicit top-level package boundaries
disabled_rules = ["PA010"]            # rule codes to skip
```

`roots` fixes ambiguous layouts (e.g. `src/`) where the first dotted
segment alone can't tell packages apart — see `modules.top_level_package`.

## Suppressing a single line

Any diagnostic (cross-package PA001/PA002, PA01x, PA003…) can be silenced
inline, without touching `disabled_rules`:

```python
from alpha.core import helper  # pyaccess: ignore[PA001]

@public
def _secret(): ...             # pyaccess: ignore  (silences every code on this line)
```

## PA003 — visibility vs. naming mismatch

Flags a decorator/annotation that disagrees with the leading-underscore
convention: `@public def _secret()` (error — the underscore says hidden,
the decorator says public) and `@internal def helper()` (warning — no
underscore, so it reads like public API). The LSP quick fix can flip the
decorator to match, or suppress the line.
