#!/usr/bin/env python3
"""
Evaluate skill triggering against eval_queries.json files.

For each query, present every skill's name + description to a Claude
model and ask which one (if any) best matches. Compare the model's
choice against ground truth:

- A query with should_trigger=true in skill X's eval file expects the
  model to choose X.
- A query with should_trigger=false in skill X's eval file expects the
  model to choose anything other than X (another bundled skill, or
  "none").

Usage:
    ANTHROPIC_API_KEY=sk-... tools/eval_runner.py
    tools/eval_runner.py --model claude-haiku-4-5-20251001 --skill samply-recording
    tools/eval_runner.py --dry-run     # skip API calls, just validate file shapes

Exits non-zero if any query fails. Prints a per-skill summary plus the
text of every failure for review.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
NONE_CHOICE = "none"


def parse_frontmatter(skill_md: Path) -> Dict[str, str]:
    """Extract `name:` and `description:` from a SKILL.md frontmatter block."""
    text = skill_md.read_text()
    if not text.startswith("---"):
        raise ValueError(f"{skill_md}: missing frontmatter")
    end = text.find("---", 3)
    if end == -1:
        raise ValueError(f"{skill_md}: unterminated frontmatter")
    body = text[3:end]
    fields: Dict[str, str] = {}
    for line in body.splitlines():
        m = re.match(r"^(name|description):\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    if "name" not in fields or "description" not in fields:
        raise ValueError(f"{skill_md}: name and description required")
    return fields


def load_skills() -> List[Dict[str, Any]]:
    skills = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        eval_path = skill_dir / "eval_queries.json"
        if not skill_md.exists() or not eval_path.exists():
            continue
        meta = parse_frontmatter(skill_md)
        queries = json.loads(eval_path.read_text())
        skills.append({
            "name": meta["name"],
            "description": meta["description"],
            "queries": queries,
            "dir": skill_dir,
        })
    return skills


def build_prompt(query: str, skills: List[Dict[str, Any]]) -> str:
    options = "\n\n".join(
        f"- {s['name']}: {s['description']}" for s in skills
    )
    return (
        "You are routing a user message to the most appropriate skill.\n"
        "Each skill is described below. Pick exactly one skill name, or "
        f"the literal word `{NONE_CHOICE}` if no skill applies.\n\n"
        f"Skills:\n{options}\n\n"
        f"User message: {query!r}\n\n"
        "Respond with ONLY the skill name or `none` — no explanation."
    )


def call_claude(prompt: str, model: str, api_key: str) -> str:
    payload = json.dumps({
        "model": model,
        "max_tokens": 64,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    blocks = body.get("content") or []
    for block in blocks:
        if block.get("type") == "text":
            return block.get("text", "").strip()
    return ""


def normalize_choice(text: str, valid_names: List[str]) -> str:
    """Pull a known skill name (or `none`) out of the model's reply."""
    lowered = text.strip().strip("`'\"").lower()
    if lowered.startswith(NONE_CHOICE):
        return NONE_CHOICE
    for name in valid_names:
        if lowered == name.lower() or lowered.startswith(name.lower()):
            return name
    # last-ditch: any name appearing as a substring
    for name in valid_names:
        if name.lower() in lowered:
            return name
    return text.strip()


def evaluate(
    skills: List[Dict[str, Any]],
    *,
    model: str,
    api_key: Optional[str],
    skill_filter: Optional[str],
    dry_run: bool,
) -> int:
    valid_names = [s["name"] for s in skills]
    failures: List[str] = []
    counts: Dict[str, Tuple[int, int]] = {}

    for skill in skills:
        if skill_filter and skill["name"] != skill_filter:
            continue
        passed = 0
        total = 0
        for entry in skill["queries"]:
            query = entry["query"]
            expected_match = bool(entry["should_trigger"])
            total += 1
            if dry_run:
                passed += 1
                continue
            assert api_key is not None
            try:
                raw = call_claude(build_prompt(query, skills), model, api_key)
            except urllib.error.HTTPError as exc:
                sys.exit(f"API error ({exc.code}): {exc.read().decode('utf-8', 'replace')}")
            choice = normalize_choice(raw, valid_names)
            chose_this = choice == skill["name"]
            if chose_this == expected_match:
                passed += 1
            else:
                failures.append(
                    f"[{skill['name']}] query={query!r}\n"
                    f"  expected_match={expected_match} got={choice!r} (raw={raw!r})"
                )
        counts[skill["name"]] = (passed, total)

    for name, (passed, total) in counts.items():
        marker = "OK" if passed == total else "FAIL"
        print(f"{marker} {name}: {passed}/{total}")

    if failures:
        print("\nFailures:")
        for f in failures:
            print(f)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Default: {DEFAULT_MODEL}")
    parser.add_argument(
        "--skill",
        default=None,
        help="Only evaluate this skill name (default: all).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip API calls; just verify each eval_queries.json loads and frontmatter parses.",
    )
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not args.dry_run and not api_key:
        sys.exit("Set ANTHROPIC_API_KEY (or pass --dry-run).")

    skills = load_skills()
    if not skills:
        sys.exit("No skills found under skills/")
    return evaluate(
        skills,
        model=args.model,
        api_key=api_key,
        skill_filter=args.skill,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
