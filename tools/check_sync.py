#!/usr/bin/env python3
"""
Verify that files shared across skills are byte-identical.

Each skill must remain self-contained at install time (users copy a skill
directory into their agent client), so we duplicate `profile_common.py` and
`merge_syms.py` rather than symlink. This script enforces no drift.

Run from the repo root:

    tools/check_sync.py            # verify
    tools/check_sync.py --write    # rewrite copies from canonical

Exit 0 if all groups match; exit 1 otherwise.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"

# (canonical, [copies...])
GROUPS: List[Tuple[Path, List[Path]]] = [
    (
        SKILLS / "samply-hotspots/scripts/profile_common.py",
        [SKILLS / "samply-diffing/scripts/profile_common.py"],
    ),
    (
        SKILLS / "samply-hotspots/scripts/merge_syms.py",
        [
            SKILLS / "samply-diffing/scripts/merge_syms.py",
            SKILLS / "samply-recording/scripts/merge_syms.py",
        ],
    ),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Overwrite copies from canonical instead of just verifying.",
    )
    args = parser.parse_args()

    failures: List[str] = []
    for canonical, copies in GROUPS:
        if not canonical.exists():
            failures.append(f"missing canonical: {canonical}")
            continue
        canonical_hash = sha256(canonical)
        for copy in copies:
            if args.write:
                shutil.copyfile(canonical, copy)
                print(f"wrote {copy} <- {canonical}")
                continue
            if not copy.exists():
                failures.append(f"missing copy: {copy}")
                continue
            if sha256(copy) != canonical_hash:
                failures.append(
                    f"drift: {copy} differs from {canonical}\n"
                    f"  fix with: tools/check_sync.py --write"
                )

    if failures:
        for f in failures:
            print(f, file=sys.stderr)
        return 1
    if not args.write:
        print(f"ok: {sum(len(c) for _, c in GROUPS)} copies in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
