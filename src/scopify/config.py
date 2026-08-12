"""Project-wide Scopify configuration.

Looks for a standalone ``scopify.toml`` first, then falls back to a
``[tool.scopify]`` table in ``pyproject.toml``. Currently supports a single
setting, per roadmap §4.1:

* ``default_visibility`` — the visibility assumed for a symbol that carries
  no ``@public``/``@internal``/``@private`` decorator at all. ``"public"``
  (the default) suits gradual adoption on an existing codebase; ``"internal"``
  is the stricter setting recommended once a project wants every public API
  surface to be explicit.
* ``roots`` — explicit dotted-prefix list of the top-level package
  boundaries used by SC001. Overrides the default heuristic (first dotted
  segment of the module name), which collapses when the analysis root isn't
  the direct parent of the packages (e.g. a ``src/`` layout or a monorepo
  scanned from its top).
* ``disabled_rules`` — rule codes (e.g. ``"SC010"``) to skip entirely.
* ``severity`` — per-rule severity overrides. Maps rule codes to one of
  ``"error"`` (default), ``"warning"``, ``"hint"``, or ``"none"`` (silences
  the rule, equivalent to adding it to ``disabled_rules``).

  Example::

      [tool.scopify.severity]
      SC017 = "warning"
      SC003 = "hint"

CLI overrides (via :func:`merge_cli_overrides`) take precedence over any
file-based setting so that one-off runs (``--disable SC014``, CI invocations
with a specific ``--default-visibility``) never require touching the project
config.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

try:
    import tomllib  # Python >= 3.11 (stdlib)
except ModuleNotFoundError:  # pragma: no cover - only exercised on Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

from scopify.markers import Visibility

_DEFAULT_VISIBILITY = Visibility.PUBLIC
_VALID_DEFAULTS = {"public": Visibility.PUBLIC, "internal": Visibility.INTERNAL}
_VALID_SEVERITIES = {"error", "warning", "hint", "none"}


@dataclass(frozen=True)
class ScopifyConfig:
    default_visibility: Visibility = _DEFAULT_VISIBILITY
    roots: tuple[str, ...] = ()
    disabled_rules: frozenset[str] = field(default_factory=frozenset)
    # Maps rule codes to severity overrides. "none" silences the rule.
    severity: dict[str, str] = field(default_factory=dict)


def _parse_default_visibility(raw: object, *, source: Path) -> Visibility:
    if raw is None:
        return _DEFAULT_VISIBILITY
    if not isinstance(raw, str) or raw not in _VALID_DEFAULTS:
        raise ValueError(
            f"{source}: 'default_visibility' must be one of "
            f"{sorted(_VALID_DEFAULTS)!r}, got {raw!r}."
        )
    return _VALID_DEFAULTS[raw]


def _parse_str_list(raw: object, *, key: str, source: Path) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw):
        raise ValueError(f"{source}: '{key}' must be a list of strings, got {raw!r}.")
    return tuple(raw)


def _parse_severity(raw: object, *, source: Path) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"{source}: 'severity' must be a table mapping rule codes to severity "
            f"levels, got {raw!r}."
        )
    result: dict[str, str] = {}
    for code, level in raw.items():
        if not isinstance(code, str):
            raise ValueError(
                f"{source}: 'severity' keys must be strings (rule codes), got {code!r}."
            )
        if not isinstance(level, str) or level not in _VALID_SEVERITIES:
            raise ValueError(
                f"{source}: 'severity[{code}]' must be one of "
                f"{sorted(_VALID_SEVERITIES)!r}, got {level!r}."
            )
        result[code] = level
    return result


def _config_from_mapping(data: dict, *, source: Path) -> ScopifyConfig:
    return ScopifyConfig(
        default_visibility=_parse_default_visibility(
            data.get("default_visibility"), source=source
        ),
        roots=_parse_str_list(data.get("roots"), key="roots", source=source),
        disabled_rules=frozenset(
            _parse_str_list(data.get("disabled_rules"), key="disabled_rules", source=source)
        ),
        severity=_parse_severity(data.get("severity"), source=source),
    )


def load_config(root: Path) -> ScopifyConfig:
    """Load Scopify configuration for a project rooted at ``root``.

    Returns defaults if neither ``scopify.toml`` nor a ``[tool.scopify]``
    section in ``pyproject.toml`` is found, or a key is simply absent.
    """
    root = Path(root)

    standalone = root / "scopify.toml"
    if standalone.is_file():
        data = tomllib.loads(standalone.read_text(encoding="utf-8"))
        return _config_from_mapping(data, source=standalone)

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        tool_section = data.get("tool", {}).get("scopify", {})
        return _config_from_mapping(tool_section, source=pyproject)

    return ScopifyConfig()


def merge_cli_overrides(
    base: ScopifyConfig,
    *,
    default_visibility: str | None = None,
    roots: list[str] | None = None,
    disable: list[str] | None = None,
) -> ScopifyConfig:
    """Return a new config with CLI-supplied values merged over ``base``.

    Only non-``None`` arguments override the corresponding field; absent
    arguments leave the file-based (or default) value untouched.  Extra
    disabled rules accumulate on top of those already in ``base``.
    """
    overrides: dict = {}
    if default_visibility is not None:
        if default_visibility not in _VALID_DEFAULTS:
            raise ValueError(
                f"--default-visibility must be one of {sorted(_VALID_DEFAULTS)!r}, "
                f"got {default_visibility!r}."
            )
        overrides["default_visibility"] = _VALID_DEFAULTS[default_visibility]
    if roots is not None:
        overrides["roots"] = tuple(roots)
    if disable:
        overrides["disabled_rules"] = base.disabled_rules | frozenset(disable)
    return replace(base, **overrides)
