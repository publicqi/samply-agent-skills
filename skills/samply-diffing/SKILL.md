---
name: samply-diffing
description: Use this skill when the user wants to compare two samply or Firefox processed profiles from before/after a code change, benchmark run, test run, or configuration change. It normalizes by weighted sample share, matches logical threads across captures, and reports regressions and improvements for leaf hotspots, inclusive hotspots, and repeated stacks so the agent can judge whether an optimization worked or just moved work elsewhere.
license: Apache-2.0
metadata:
  author: OpenAI
  version: "1.0.0"
---

# Goal

Compare two saved profiles in a way that is robust to different run lengths and sample counts.

# Default command

```bash
scripts/compare_profiles.py baseline.profile.json.gz candidate.profile.json.gz > diff.json
```

For a readable summary:

```bash
scripts/compare_profiles.py --format markdown baseline.profile.json.gz candidate.profile.json.gz
```

# Comparison discipline

- Compare **percent share of weighted samples**, not raw sample counts.
- Read **leaf**, **inclusive**, and **stack** deltas together. A change may simply move cost from one leaf frame to another.
- Prefer comparisons from similar workloads, inputs, and build settings.
- Treat weak symbol coverage as a data-quality problem before treating it as a regression.
- If thread names are duplicated across processes, include the process name in your conclusions.

# What the script reports

The diff includes:

- baseline and candidate sample totals
- global regressions and improvements
- per-thread regressions and improvements
- separate sections for leaf functions, inclusive functions, and full stacks

# Interpreting deltas

A positive delta means the candidate consumed a larger share of samples than the baseline. That is usually a regression for CPU cost.

A negative delta means the candidate consumed a smaller share. That is usually an improvement, but verify that work did not simply move into another function or thread.

# Reliability checks

Be cautious when:

- the two runs exercised different code paths
- either profile has very few samples
- symbols differ substantially between runs
- one profile was recorded with thread filters and the other was not

# Reference

For normalization details and thread matching assumptions, read:

- `references/DIFFING.md`
