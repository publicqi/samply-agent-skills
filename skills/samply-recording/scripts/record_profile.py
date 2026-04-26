#!/usr/bin/env python3
"""
Agent-friendly wrapper around `samply record`.

Handles four pieces of friction that come up when an agent records a
profile non-interactively:

1. forces `--save-only` and an explicit `-o <path>` (default
   `profile.json.gz`) so nothing opens a browser
2. auto-adds `--unstable-presymbolicate` when the installed samply
   supports it (override with `--no-presymbolicate`)
3. on macOS, optionally regenerates a `.dSYM` for a Rust/C++ binary
   before recording (`--regen-dsym <binary>`)
4. for long-running children, sends SIGINT to the **child** (never
   samply) after `--max-duration` seconds so samply can finalize and
   write the profile — see references/RECORDING.md for why this is
   needed instead of `-d N`

Examples:

    record_profile.py -- ./target/profiling/my-bench
    record_profile.py -o bench.profile.json.gz --max-duration 30 -- ./my-server
    record_profile.py --pid 12345 --max-duration 10
    record_profile.py --regen-dsym ./target/profiling/my-bench -- ./target/profiling/my-bench
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

DEFAULT_OUTPUT = "profile.json.gz"
PRESYM_FLAG_PRIMARY = "--unstable-presymbolicate"
PRESYM_FLAG_FALLBACK = "--presymbolicate"


def samply_supports(flag: str) -> bool:
    proc = subprocess.run(
        ["samply", "record", "--help"], capture_output=True, text=True, check=False
    )
    return flag in (proc.stdout or "") + (proc.stderr or "")


def regen_dsym(binary: Path) -> None:
    if platform.system() != "Darwin":
        print(f"--regen-dsym ignored on {platform.system()}", file=sys.stderr)
        return
    if not binary.exists():
        sys.exit(f"--regen-dsym: binary not found: {binary}")
    if not shutil.which("dsymutil"):
        sys.exit("--regen-dsym: dsymutil not on PATH (xcode-select --install)")
    dsym = binary.with_suffix(binary.suffix + ".dSYM")
    if dsym.exists():
        shutil.rmtree(dsym)
    subprocess.run(["dsymutil", str(binary)], check=True)
    print(f"regenerated {dsym}", file=sys.stderr)


def find_samply_child(samply_pid: int, timeout: float = 5.0) -> Optional[int]:
    """Poll for samply's first child via `pgrep -P`. Cross-platform on linux/macOS."""
    if not shutil.which("pgrep"):
        return None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        proc = subprocess.run(
            ["pgrep", "-P", str(samply_pid)], capture_output=True, text=True, check=False
        )
        line = (proc.stdout or "").strip().splitlines()
        if line:
            try:
                return int(line[0])
            except ValueError:
                pass
        time.sleep(0.2)
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Profile output path. Default: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--pid",
        type=int,
        default=None,
        help="Attach to a running PID instead of launching a child.",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "After SECONDS, send SIGINT to the profiled child (not to samply) "
            "so samply finalizes and writes the profile. Required for "
            "long-running daemons / REPLs / event loops."
        ),
    )
    parser.add_argument(
        "--no-presymbolicate",
        action="store_true",
        help="Do not pass --unstable-presymbolicate even if available.",
    )
    parser.add_argument(
        "--regen-dsym",
        metavar="BINARY",
        default=None,
        help="(macOS) Regenerate <BINARY>.dSYM with dsymutil before recording.",
    )
    parser.add_argument(
        "--extra",
        action="append",
        default=[],
        metavar="FLAG",
        help="Extra flag to pass through to samply record (repeatable).",
    )
    parser.add_argument(
        "child",
        nargs=argparse.REMAINDER,
        help="Command to run after `--`. Required unless --pid is given.",
    )
    return parser.parse_args()


def build_command(args: argparse.Namespace) -> List[str]:
    cmd = ["samply", "record", "--save-only", "-o", args.output]
    if not args.no_presymbolicate:
        if samply_supports(PRESYM_FLAG_PRIMARY):
            cmd.append(PRESYM_FLAG_PRIMARY)
        elif samply_supports(PRESYM_FLAG_FALLBACK):
            cmd.append(PRESYM_FLAG_FALLBACK)
    cmd.extend(args.extra)
    if args.pid is not None:
        cmd.extend(["-p", str(args.pid)])
    else:
        child = list(args.child)
        if child and child[0] == "--":
            child = child[1:]
        if not child:
            sys.exit("record_profile.py: pass a command after `--` or use --pid")
        cmd.append("--")
        cmd.extend(child)
    return cmd


def main() -> int:
    args = parse_args()

    if not shutil.which("samply"):
        sys.exit("samply not found on PATH; install with `cargo install samply --locked`")

    if args.regen_dsym:
        regen_dsym(Path(args.regen_dsym))

    cmd = build_command(args)
    print(f"+ {' '.join(cmd)}", file=sys.stderr)

    proc = subprocess.Popen(cmd)
    if args.max_duration is None:
        return proc.wait()

    target_pid = args.pid if args.pid is not None else find_samply_child(proc.pid)
    if target_pid is None:
        print(
            "warning: could not find profiled child PID for SIGINT; "
            "letting samply run until the child exits on its own.",
            file=sys.stderr,
        )
        return proc.wait()

    try:
        proc.wait(timeout=args.max_duration)
        return proc.returncode
    except subprocess.TimeoutExpired:
        pass

    print(
        f"max-duration reached; sending SIGINT to child pid {target_pid}",
        file=sys.stderr,
    )
    try:
        os.kill(target_pid, signal.SIGINT)
    except ProcessLookupError:
        print(f"child pid {target_pid} already gone", file=sys.stderr)
    return proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
