"""Minimal CLI: ``scopify check <path>``."""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from scopify.baseline import filter_new, load_baseline, write_baseline
from scopify.config import load_config, merge_cli_overrides
from scopify.diagnostics import Diagnostic
from scopify.docs import get_rule, list_rules
from scopify.engine import check_project
from scopify.zones import analyse as analyse_zones
from scopify.zones import format_text as format_zones
from scopify.zones import to_dict as zones_to_dict

_DEFAULT_BASELINE = "scopify-baseline.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scopify", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="Check a project for accessibility violations.")
    check.add_argument("path", type=Path, help="Project root to analyse.")
    check.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    check.add_argument(
        "--disable",
        metavar="RULE",
        action="append",
        default=[],
        help="Disable a rule for this run (e.g. --disable SC014). Repeatable.",
    )
    check.add_argument(
        "--default-visibility",
        choices=("public", "internal"),
        default=None,
        help="Override default_visibility for this run.",
    )
    check.add_argument(
        "--root",
        metavar="PKG",
        action="append",
        default=None,
        dest="roots",
        help="Override the project boundaries for @internal (e.g. --root src.pkgA). Repeatable.",
    )
    check.add_argument(
        "--write-baseline",
        metavar="FILE",
        nargs="?",
        const=_DEFAULT_BASELINE,
        default=None,
        help=(
            "Write current violations to a baseline file and exit 0. "
            f"Defaults to {_DEFAULT_BASELINE!r} when no FILE is given."
        ),
    )
    check.add_argument(
        "--baseline",
        metavar="FILE",
        default=None,
        help=(
            "Path to a baseline file produced by --write-baseline. "
            "Only violations absent from the baseline are reported."
        ),
    )

    explain = sub.add_parser(
        "explain",
        help="Show documentation for one or all rules.",
    )
    explain.add_argument(
        "code",
        nargs="?",
        metavar="CODE",
        help="Rule code to explain (e.g. SC017). Omit to list all rules.",
    )

    zones = sub.add_parser(
        "zones",
        help="Show the layers a project splits into, and the dependency knots.",
    )
    zones.add_argument("path", type=Path, help="Project root to analyse.")
    zones.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    zones.add_argument(
        "--root",
        metavar="PKG",
        action="append",
        default=None,
        dest="roots",
        help="Restrict the analysis to these top-level packages. Repeatable.",
    )
    zones.add_argument(
        "--no-layers",
        action="store_true",
        help="Only report the dependency knots, without listing every layer.",
    )

    return parser


def _to_json(diagnostics: list[Diagnostic]) -> str:
    payload = [
        {
            "code": d.code,
            "severity": d.severity,
            "message": d.message,
            "file": str(d.file),
            "line": d.line,
            "column": d.column,
        }
        for d in diagnostics
    ]
    return json.dumps(payload, indent=2)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "check":
        base_config = load_config(args.path)
        config = merge_cli_overrides(
            base_config,
            default_visibility=args.default_visibility,
            roots=args.roots,
            disable=args.disable,
        )
        diagnostics = check_project(args.path, config=config)

        # --write-baseline: dump current violations and exit 0
        if args.write_baseline is not None:
            baseline_path = Path(args.write_baseline)
            write_baseline(diagnostics, args.path, baseline_path)
            print(
                f"scopify: baseline written to {baseline_path} "
                f"({len(diagnostics)} violation(s) recorded)."
            )
            return 0

        # --baseline: filter out known violations
        if args.baseline is not None:
            baseline_path = Path(args.baseline)
            if not baseline_path.is_file():
                print(
                    f"scopify: baseline file not found: {baseline_path}. "
                    "Run --write-baseline first.",
                    file=sys.stderr,
                )
                return 2
            try:
                baseline = load_baseline(baseline_path)
            except (ValueError, KeyError) as exc:
                print(f"scopify: {exc}", file=sys.stderr)
                return 2
            diagnostics = filter_new(diagnostics, args.path, baseline)

        if args.format == "json":
            print(_to_json(diagnostics))
        else:
            for diag in diagnostics:
                print(diag.format())
            if not diagnostics:
                print("scopify: 0 issue found.")
            else:
                print(f"scopify: {len(diagnostics)} issue(s) found.")
        return 0 if not diagnostics else 1

    if args.command == "explain":
        return _handle_explain(args)

    if args.command == "zones":
        return _handle_zones(args)

    parser.error(f"unknown command: {args.command}")
    return 2


def _handle_zones(args: argparse.Namespace) -> int:
    """``scopify zones`` is a diagnostic, never a gate.

    It always exits 0. Removing a module that half the project imports does
    shift which imports are reported, so failing a build on that would blame
    whoever happened to touch the crossroads.
    """
    config = merge_cli_overrides(load_config(args.path), roots=args.roots)
    report = analyse_zones(args.path, config=config)
    if args.format == "json":
        print(json.dumps(zones_to_dict(report), indent=2))
    else:
        print(format_zones(report, show_layers=not args.no_layers))
    return 0


def _handle_explain(args: argparse.Namespace) -> int:
    if args.code is None:
        # List all rules with a one-line summary.
        rules = list_rules()
        width = max(len(r.code) for r in rules)
        for r in rules:
            sev = f"[{r.severity}]"
            print(f"  {r.code:<{width}}  {sev:<9}  {r.title}")
        print(f"\n  {len(rules)} rules. Run 'scopify explain <CODE>' for full details.")
        return 0

    rule = get_rule(args.code)
    if rule is None:
        print(f"scopify: unknown rule code {args.code!r}.", file=sys.stderr)
        print("Run 'scopify explain' (no argument) to list all known rules.", file=sys.stderr)
        return 2
    print(rule.render())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


