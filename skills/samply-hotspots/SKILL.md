---
name: samply-hotspots
description: Use this skill when the user already has a samply or Firefox processed profile (`profile.json`, `profile.json.gz`, or similar) and wants machine-readable hotspots, stack summaries, ranked threads, marker counts, or actionable findings without manually reading Firefox Profiler. It converts the processed profile format into compact JSON or Markdown with leaf hotspots, inclusive hotspots, dominant stacks, symbol-coverage checks, and notes about low-sample or weak-symbol captures.
license: Apache-2.0
metadata:
  author: OpenAI
  version: "1.0.0"
---

# Goal

Turn a saved samply profile into a compact report that an agent can reason over directly.

# Default command

```bash
scripts/summarize_profile.py path/to/profile.json.gz > summary.json
```

For a human-readable report:

```bash
scripts/summarize_profile.py --format markdown path/to/profile.json.gz
```

If the profile was recorded with `samply record --unstable-presymbolicate`,
the resolved symbols live in a sidecar file (`<profile>.syms.json`) next
to the profile. `summarize_profile.py` auto-merges that sidecar at load
time, so you do not need to run a separate merge step. To produce a
merged single-file profile for other tools, use
`scripts/merge_syms.py <profile.json.gz>`.

# How to interpret the output

Use the report in this order:

1. **Thread ranking** — find where the samples concentrate.
2. **Leaf hotspots** — what was sampled at the tip of the stack.
3. **Inclusive hotspots** — what code dominates full stacks, even when not the leaf.
4. **Top stacks** — repeated stack shapes often reveal phase-specific work or lock contention paths.
5. **Markers** — useful when the profile contains phase or task markers.

# Required discipline

- Prefer JSON for downstream machine consumption.
- Do not over-interpret tiny profiles. The script emits notes when sample counts are very low.
- Check `leaf_symbol_coverage_pct`. If symbol coverage is poor, fix recording or symbols before drawing conclusions.
- Treat unsymbolicated hex addresses and `?` frames as recording quality problems, not performance findings.
- Use thread names plus process names when describing hotspots; many profiles contain repeated thread names across processes.

# Useful flags

```bash
scripts/summarize_profile.py   --top-threads 12   --top-functions 15   --top-stacks 10   --top-markers 10   path/to/profile.json.gz
```

# Output contract

The JSON report contains:

- global thread ranking
- per-thread weighted sample totals
- top leaf functions
- top inclusive functions
- top stacks
- top markers
- symbol coverage and notes

This is deliberately much smaller and more stable than the raw Firefox processed profile.

# When to stop and re-record

Stop and improve the profile instead of analyzing further when:

- symbol coverage is poor
- almost all hotspots are raw addresses or `?`
- the target thread barely has any samples
- the user needs off-CPU data from Linux

# Reference

If the parser needs maintenance or the raw profile structure matters, read:

- `references/PROFILE-FORMAT.md`
