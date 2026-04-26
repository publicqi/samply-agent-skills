# Design rationale

## What makes a good skill here

The Agent Skills spec and guidance reward compact metadata, stepwise SKILL bodies, progressive disclosure, and agent-friendly scripts. In practice that means:

- narrow, triggerable scopes instead of a giant “do everything with samply” skill
- imperative descriptions focused on user intent
- deterministic structured output
- reference files for detail that should not always sit in the agent context
- scripts that expose `--help`, avoid interactive prompts, and emit machine-readable stdout

## Why samply needs help for agent use

Samply is not broken for agents; it is simply optimized for a different consumer:

- **Humans** want Firefox Profiler's UI, rich flame graphs, source view, and symbol server integration.
- **Agents** want stable files, low-context summaries, and repeatable comparisons.

The most important mismatch is the processed profile JSON. It is efficient for the Firefox Profiler app because samples, stacks, frames, functions, resources, and strings are spread across multiple index tables. For an agent, that forces non-trivial reconstruction before it can even answer simple questions like “what are the hottest leaf functions on the busiest thread?”.

## Why three skills instead of one

A single skill would have weaker triggering and a noisier instruction set. Splitting the workflow yields cleaner activation boundaries:

- `samply-recording` for capture and environment triage
- `samply-hotspots` for one-profile analysis
- `samply-diffing` for before/after comparison

That mirrors how users usually ask for help, and it keeps each description specific enough to trigger reliably.

## What these scripts intentionally do not do

- They do **not** replace Firefox Profiler for rich visual inspection.
- They do **not** attempt perfect wall-time attribution.
- They do **not** mutate profiles or upload them anywhere.
- They do **not** depend on non-standard Python packages.

## Where to extend next

Natural follow-ons would be:

- a `samply-callgrind-export` skill, if samply later grows first-party export support
- optional CSV output for spreadsheet-based regression dashboards
- symbolication quality reports split by library/module
