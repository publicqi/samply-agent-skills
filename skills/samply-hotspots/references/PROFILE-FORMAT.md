# Firefox processed profile notes for samply users

This skill summarizes the **processed profile** JSON that Firefox Profiler consumes and that samply emits or serves.

## Why the raw format is awkward for agents

The processed profile format is optimized for browser performance, not agent readability. Instead of a straightforward list of sample objects, it uses several index-based tables such as:

- `stringTable`
- `funcTable`
- `frameTable`
- `stackTable`
- `resourceTable`
- `samples`
- `markers`

To understand one sample, you often have to follow multiple table lookups:

1. sample -> stack index
2. stack -> frame index + parent stack
3. frame -> function index
4. function -> string index
5. string table -> symbol text

That design is efficient for the Firefox Profiler UI, but it pushes significant reconstruction work onto an LLM.

## What the summarizer script does

`scripts/summarize_profile.py` reconstructs stacks and reports only what tends to matter for diagnosis:

- which threads dominate the capture
- top leaf functions
- top inclusive functions
- repeated full stacks
- marker frequencies
- symbol quality warnings

The output is deterministic and compact so agents can diff, filter, and reason over it.

## Leaf vs inclusive

Leaf hotspot:
- counts only when the function appears at the sampled tip of the stack
- useful for seeing where CPU time ends up

Inclusive hotspot:
- counts whenever the function appears anywhere in the sampled stack
- useful for seeing which subsystems dominate call paths

You often need both. A scheduler, allocator, or lock primitive may dominate leaf samples while a higher-level subsystem dominates inclusive samples.

## Limitations

- Sampling profilers are statistical.
- Linux captures on-CPU samples only.
- Unsymbolicated frames can skew hotspot rankings.
- The script aggregates by observed sample weights and does not infer wall time from them.
- Marker semantics depend on what the profiled program or importer emitted.

## Maintenance notes

The parser supports two common table layouts:
- columnar arrays plus `length`
- `schema` plus `data`

If future Firefox Profiler changes add fields, the summarizer should usually continue working because it only reads a small stable subset of the tables.
