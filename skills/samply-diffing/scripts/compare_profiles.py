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
        help="Maximum number of regressions and improvements to keep per section. Default: 15",
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
