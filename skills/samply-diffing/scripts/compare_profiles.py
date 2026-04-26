#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

from profile_common import (
    analyze_profile,
    build_diff_report,
    load_profile,
    render_diff_markdown,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two samply / Firefox processed profiles using normalized percentages."
        )
    )
    parser.add_argument("baseline", help="Path to the baseline profile (.json or .json.gz)")
    parser.add_argument("candidate", help="Path to the candidate profile (.json or .json.gz)")
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Output format. Default: json",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=15,
        help=(
            "Default cap for regressions/improvements per section. "
            "Overridden by --top-functions and --top-stacks. Default: 15"
        ),
    )
    parser.add_argument(
        "--top-functions",
        type=int,
        default=None,
        help="Cap for leaf and inclusive function regressions/improvements. Default: --top",
    )
    parser.add_argument(
        "--top-stacks",
        type=int,
        default=None,
        help="Cap for full-stack regressions/improvements. Default: --top",
    )
    parser.add_argument(
        "--thread",
        action="append",
        default=[],
        metavar="QUERY",
        help=(
            "Restrict to threads whose process_name or name contains QUERY "
            "(case-insensitive substring). Repeat to keep multiple threads. "
            "Aggregated thread keys are matched, so tids are not part of the haystack."
        ),
    )
    parser.add_argument(
        "--strict-coverage",
        action="store_true",
        help=(
            "Exit non-zero (3) when leaf symbol coverage is poor on both sides "
            "for every returned thread. Useful to fail fast in scripts before "
            "trusting deltas."
        ),
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="Indentation to use for JSON output. Default: 2",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        baseline_profile = load_profile(args.baseline)
        candidate_profile = load_profile(args.candidate)
        baseline_analysis = analyze_profile(baseline_profile)
        candidate_analysis = analyze_profile(candidate_profile)
        report = build_diff_report(
            baseline_analysis,
            candidate_analysis,
            baseline_source=args.baseline,
            candidate_source=args.candidate,
            top=args.top,
            top_functions=args.top_functions,
            top_stacks=args.top_stacks,
            thread_filters=args.thread,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(
            f"Error: failed to parse profile JSON near line {exc.lineno}, column {exc.colno}: {exc.msg}",
            file=sys.stderr,
        )
        return 2
    except OSError as exc:
        print(f"Error: failed to read profile: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error: unexpected failure while diffing profiles: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        json.dump(report, sys.stdout, indent=args.indent, sort_keys=False)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_diff_markdown(report))

    poor_coverage = any(
        "poor leaf symbol coverage" in note.lower()
        for note in report.get("notes", [])
    )
    if poor_coverage:
        print(
            "WARNING: leaf symbol coverage is poor on both sides for every "
            "returned thread. Diff deltas may be misleading. Regenerate the "
            ".dSYM, re-record with --unstable-presymbolicate, or pass "
            "--symbol-dir before drawing conclusions.",
            file=sys.stderr,
        )
        if args.strict_coverage:
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
