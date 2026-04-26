---
name: samply-hotspots
description: Use this skill when the user already has a samply or Firefox processed profile (`profile.json`, `profile.json.gz`, or similar) and wants machine-readable hotspots, stack summaries, ranked threads, marker counts, or actionable findings without manually reading Firefox Profiler. It converts the processed profile format into compact JSON or Markdown with leaf hotspots, inclusive hotspots, dominant stacks, symbol-coverage checks, and notes about low-sample or weak-symbol captures.
---

# Goal

Turn a saved samply profile into a compact report that an agent can reason over directly.

# Default command

```bash
scripts/summarize_profile.py path/to/profile.json.gz > summary.json

# human-readable variant
scripts/summarize_profile.py --format markdown path/to/profile.json.gz
```

If the profile was recorded with `--unstable-presymbolicate`, the resolved symbols live in a sibling `<profile>.syms.json` sidecar; the summarizer auto-merges it at load time. To produce a one-shot merged profile for tools that do not share the auto-merge, run `scripts/merge_syms.py <profile.json.gz>`.

# How to interpret the output

1. **Thread ranking** — find where the samples concentrate.
2. **Leaf hotspots** — what was sampled at the tip of the stack.
3. **Inclusive hotspots** — what code dominates full stacks even when not the leaf.
4. **Top stacks** — repeated stack shapes often reveal phase-specific work or lock contention.
5. **Markers** — useful when the profile contains phase or task markers.

# Required discipline

- Prefer JSON for downstream machine consumption.
- Check `leaf_symbol_coverage_pct`. If coverage is poor, fix recording or symbols before drawing conclusions.
- Treat unsymbolicated hex addresses and `?` frames as recording quality problems, not performance findings.
- Use thread names plus process names; many profiles repeat thread names across processes.
- Do not over-interpret tiny profiles. The script emits notes when sample counts are low.

# Useful flags

```bash
scripts/summarize_profile.py \
  --top-threads 12 --top-functions 15 --top-stacks 10 --top-markers 10 \
  path/to/profile.json.gz

# restrict to specific threads (case-insensitive substring vs process_name / name / tid; repeatable)
scripts/summarize_profile.py --thread mininerv-cli --thread token-worker path/to/profile.json.gz

# roll up worker pools: when N threads share a name (e.g. 32 worker / 8 encoder
# threads), --family aggregates them into one "{family}: N threads, X% combined"
# row with combined leaf / inclusive hotspots. Repeatable for multiple families.
scripts/summarize_profile.py --family worker --family encoder path/to/profile.json.gz

# fail fast in scripts when leaf coverage is too poor to trust rankings
scripts/summarize_profile.py --strict-coverage path/to/profile.json.gz || echo "regenerate dSYM / re-record with --unstable-presymbolicate"
```

`--strict-coverage` exits 3 (instead of 0) and prints a stderr banner.

# Output contract

The JSON report contains a `schema` field (`{"name": "samply-hotspots-summary", "version": 1}`) plus a global thread ranking, per-thread weighted sample totals, top leaf functions, top inclusive functions, top stacks, top markers, symbol coverage notes, and (when `--family` is passed) a `family_rollups` array with combined-thread totals and combined hotspots. Pin against `schema.version` for downstream agents. The shape is deliberately much smaller and more stable than the raw Firefox processed profile.

# When to stop and re-record

Stop and improve the profile instead of analyzing further when symbol coverage is poor, almost all hotspots are raw addresses or `?`, the target thread barely has any samples, or the user needs off-CPU data from Linux.

# Hand off to samply-diffing for two-profile questions

If the user is asking whether one capture is faster/slower than another (candidate vs baseline, after-the-fix vs before, with-flag vs without-flag), do not try to eyeball it from two `summarize_profile.py` runs. Hand off to the samply-diffing skill — its share-of-samples normalization handles unequal run lengths and produces structured regression / improvement rows that this single-profile summary cannot.

# Reference

If the parser needs maintenance or the raw profile structure matters, read `references/PROFILE-FORMAT.md`.
