#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

from profile_common import analyze_profile, build_public_report, load_profile, render_markdown


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize a samply / Firefox processed profile into compact machine-readable "
            "hotspot data."
        )
    )
    parser.add_argument(
        "profile",
        help="Path to profile.json or profile.json.gz. Use '-' to read JSON or gzip-compressed JSON from stdin.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Output format. Default: json",
    )
    parser.add_argument(
        "--top-threads",
        type=int,
        default=12,
        help="Maximum number of threads to include in the report. Default: 12",
    )
    parser.add_argument(
        "--top-functions",
        type=int,
        default=15,
        help="Maximum number of leaf and inclusive functions per thread. Default: 15",
    )
    parser.add_argument(
        "--top-stacks",
        type=int,
        default=10,
        help="Maximum number of stacks per thread. Default: 10",
    )
    parser.add_argument(
        "--top-markers",
        type=int,
        default=10,
        help="Maximum number of marker names per thread. Default: 10",
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
        profile = load_profile(args.profile)
        analysis = analyze_profile(profile)
        report = build_public_report(
            analysis,
            source_path=args.profile,
            top_threads=args.top_threads,
            top_functions=args.top_functions,
            top_stacks=args.top_stacks,
            top_markers=args.top_markers,
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
        print(f"Error: unexpected failure while analyzing profile: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        json.dump(report, sys.stdout, indent=args.indent, sort_keys=False)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
