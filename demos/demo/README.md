# demo

A single, self-contained project that exercises **every Scopify rule** in
one place, with explanations inline as code comments (each offending line
carries a `# PAxxx -- why` comment, cross-referenced to the rule's
implementation under `src/scopify/rules/`).

## Layout

| Path | What it shows |
|---|---|
| `pyproject.toml` | `[tool.scopify]` config: `default_visibility`, `roots`, `disabled_rules`. |
| `core_pkg/api.py` | Declares `@public`, `@internal` and `@private` symbols — the source of truth for the two static visibility rules. |
| `core_pkg/sibling.py` | Same-package use of `@internal` symbols: **legal**, no diagnostics. |
| `core_pkg/naming_mismatches.py` | **`SC003`**: `@public`/`@internal` (decorator or `Annotated[T, Public/Internal]`) vs. leading-underscore naming. |
| `consumer_pkg/cross_package.py` | Cross-package use of the same symbols: **`SC001`** and **`SC002`** both fire here. |
| `dynamic_pkg/unresolved_attrs.py` | **`SC010`** (non-literal `getattr`/`setattr`/...), **`SC011`** (`eval`/`exec`/`compile`), **`SC012`** (non-literal `import_module`/`__import__`). |
| `dynamic_pkg/hooks.py` | **`SC013`** (module-level `__getattr__`), **`SC014`** (explicit metaclass). |
| `dynamic_pkg/mutation.py` | **`SC015`** (`__dict__` mutation), **`SC018`** (`globals()`/`locals()`/`vars()` mutation). |
| `dynamic_pkg/introspection.py` | **`SC016`** (frame introspection), **`SC017`** (monkey-patching an imported name). |
| `dynamic_pkg/escape_hatches.py` | The inline-comment and `@dynamic`-decorator suppression mechanisms. |
| `dynamic_pkg/module_marker.py` | The whole-module `# scopify: dynamic-module` suppression mechanism. |

## Configuration (`pyproject.toml`)

```toml
[tool.scopify]
default_visibility = "public"                         # symbols without a decorator are public by default
roots = ["core_pkg", "consumer_pkg", "dynamic_pkg"]    # explicit top-level package boundaries
# disabled_rules = ["SC014"]                            # rule codes to skip project-wide
```

`roots` matters most for ambiguous layouts (e.g. a `src/` directory scanned
from the repo root, where the first dotted segment alone can't tell packages
apart) — here it's a no-op since each package is already its own top-level
name, but the syntax is the same. `disabled_rules` turns off a rule code for
the whole project; it's commented out above so the demo's expected output
below stays accurate — uncomment it to see `SC014` disappear.

## Rule reference

Rules `SC001`/`SC002` need the whole-project import graph (cross-file);
`SC003` and `SC010`-`SC018` are local to a single file's AST. See
`src/scopify/rules/access.py`, `src/scopify/rules/private.py`,
`src/scopify/rules/naming.py` and `src/scopify/rules/dynamic.py` for the
authoritative implementation and docstrings behind every code below.

| Code | Meaning |
|---|---|
| `SC001` | Cross-package import of a symbol marked `@internal`. |
| `SC002` | Cross-module import of a symbol marked `@private` (stricter than `SC001`: scoped to the *module*, not the *package*). |
| `SC003` | `@public`/`@internal` annotation disagrees with leading-underscore naming (error for `@public _foo`, warning for `@internal foo`). |
| `SC010` | `getattr`/`setattr`/`hasattr`/`delattr` called with a non-literal attribute name. |
| `SC011` | `eval` / `exec` / `compile` — executes code the linter cannot see through. |
| `SC012` | `importlib.import_module` / `__import__` called with a non-literal module name. |
| `SC013` | Module-level `__getattr__` / `__getattribute__` intercepting attribute access. |
| `SC014` | A class declares an explicit custom `metaclass=...`. |
| `SC015` | Direct `__dict__` mutation (subscript write, `.update()`/`.pop()`/..., or wholesale reassignment). |
| `SC016` | Call-stack frame introspection (`inspect.currentframe`/`stack`/`trace`, `sys._getframe`). |
| `SC017` | Monkey-patching an attribute of an already-imported name. |
| `SC018` | `globals()`/`locals()`/`vars()` used for a *write* (mutator call, subscript assignment, or `del`). |

Every `PA01x` diagnostic can be silenced with one of three dynamic-rule
escape hatches (see `dynamic_pkg/escape_hatches.py` and
`dynamic_pkg/module_marker.py`):

1. An inline trailing comment: `# scopify: allow-dynamic`.
2. A `@dynamic` (or `@dynamic(reason="...")`) decorator on the enclosing
   function/class.
3. A module-level marker comment near the top of the file:
   `# scopify: dynamic-module`.

**Any** diagnostic, from any rule (`SC001`/`SC002`/`SC003`/`PA01x`), can also
be silenced with the generic inline suppression comment — see
`core_pkg/api.py`'s `helper`/`InternalRegistry` and
`core_pkg/naming_mismatches.py`'s `deliberately_unprefixed` for examples:

```python
@internal  # scopify: ignore[SC003]
def helper(): ...

@internal  # scopify: ignore   (bare form: silences every code on this line)
def other(): ...
```

## Running it

From the repository root:

```bash
scopify check demos/demo
# or, without installing the console script:
python -m scopify.cli check demos/demo
python -m scopify.cli check --format json demos/demo
```

Expected: one `SC001` and one `SC002` from `consumer_pkg/cross_package.py`,
two `SC003` (one error, one warning) from `core_pkg/naming_mismatches.py`'s
decorators plus two more from its `Annotated[...]` attributes, and one
instance each of `SC010`-`SC018` from the corresponding `dynamic_pkg/*.py`
files, but **nothing** from `core_pkg/sibling.py`,
`dynamic_pkg/escape_hatches.py`, `dynamic_pkg/module_marker.py`, or the
inline-suppressed lines in `core_pkg/api.py` and
`core_pkg/naming_mismatches.py` — those are the "this is fine"
counter-examples.

## Live underlining in an editor

See the main repository README for `scopify-lsp` setup instructions (works
with any LSP-capable editor, e.g. via the LSP4IJ plugin in PyCharm, or
natively in VS Code / Neovim). Point the language server at this single
`demos/demo` folder.
