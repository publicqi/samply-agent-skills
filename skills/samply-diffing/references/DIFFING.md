# Comparing samply profiles sanely

Raw sample counts are usually the wrong primitive for before/after analysis because captures often differ in duration, throughput, and sample volume. This skill compares **share of weighted samples** instead.

## Normalization

For each thread and for the profile globally, the script turns counters into percentages of that thread's or profile's total weighted samples.

Example:

- baseline leaf share for `foo`: 8.2%
- candidate leaf share for `foo`: 12.9%
- delta: +4.7 percentage points

That is interpretable even if one run had 20,000 samples and the other had 35,000.

## Thread matching

The script tries to aggregate by a stable logical key:

1. process name + thread name, when both exist
2. otherwise thread name

This is simple by design. It is not perfect for all workloads, but it works well enough for most before/after captures and avoids fragile heuristics.

## Why leaf + inclusive + stack all matter

- Leaf regressions reveal where samples terminate.
- Inclusive regressions reveal which subsystem now dominates call paths.
- Stack regressions reveal whether the same function got slower in a specific context.

Looking at only one of these often creates false stories.

## When not to trust the diff

Do not present a confident regression judgment when:

- symbols are mostly missing in one profile
- the candidate profile is a different phase or workload
- thread topology changed drastically for unrelated reasons
- the capture is tiny and a few samples swing percentages wildly

## Practical workflow

1. Record a baseline profile.
2. Record a candidate profile after the change.
3. Run `scripts/compare_profiles.py`.
4. Read the global regressions first.
5. Drill into the regressing threads.
6. Confirm that improvements in one area were not offset elsewhere.
