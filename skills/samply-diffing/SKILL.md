---
name: samply-diffing
description: Use this skill when the user wants to compare two samply or Firefox processed profiles from before/after a code change, benchmark run, test run, or configuration change. It normalizes by weighted sample share, matches logical threads across captures, and reports regressions and improvements for leaf hotspots, inclusive hotspots, and repeated stacks so the agent can judge whether an optimization worked or just moved work elsewhere.
---

# Goal

Compare two saved profiles in a way that is robust to different run lengths and sample counts.

# Default command

```bash
scripts/compare_profiles.py baseline.profile.json.gz candidate.profile.json.gz > diff.json

# human-readable variant
scripts/compare_profiles.py --format markdown baseline.profile.json.gz candidate.profile.json.gz
```

# Useful flags

```bash
# split caps for functions vs stacks
scripts/compare_profiles.py --top-functions 20 --top-stacks 8 baseline.profile.json.gz candidate.profile.json.gz

# restrict to specific threads (case-insensitive substring vs process_name / name; repeatable)
scripts/compare_profiles.py --thread mininerv-cli baseline.profile.json.gz candidate.profile.json.gz

# fail fast in scripts when coverage is too poor on both sides to trust the diff
scripts/compare_profiles.py --strict-coverage baseline.profile.json.gz candidate.profile.json.gz \
  || echo "regenerate dSYM / re-record with --unstable-presymbolicate"
```

`--strict-coverage` exits 3 (instead of 0) and prints a stderr banner when leaf coverage is poor on both sides for every returned thread.

# Comparison discipline

- Compare **percent share of weighted samples**, not raw counts.
- Read **leaf**, **inclusive**, and **stack** deltas together. A change may simply move cost from one leaf frame to another.
- Prefer comparisons from similar workloads, inputs, and build settings.
- Treat weak symbol coverage as a data-quality problem before treating it as a regression.
- Include the process name in conclusions when thread names repeat across processes.

# What the script reports

A `schema` field (`{"name": "samply-diff", "version": 1}`) plus baseline and candidate sample totals; global regressions and improvements; per-thread regressions and improvements; separate sections for leaf functions, inclusive functions, and full stacks. Pin against `schema.version` for downstream agents.

# Interpreting deltas

A positive delta means the candidate consumed a larger share of samples than the baseline (usually a regression for CPU cost). A negative delta means a smaller share (usually an improvement, but verify that work did not just move into another function or thread).

# Reliability checks

Be cautious when the two runs exercised different code paths, either profile has very few samples, symbols differ substantially between runs, or one profile was recorded with thread filters and the other was not.

# Reference

For normalization details and thread matching assumptions, read `references/DIFFING.md`.
