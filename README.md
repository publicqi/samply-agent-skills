# Samply Agent Skills (cr. GPT 5.4 Pro)

This bundle makes [samply](https://github.com/mstange/samply) friendlier for coding agents and other LLM-driven workflows.

## Why this exists

Samply is excellent at *recording* and *human* inspection through Firefox Profiler, but raw processed profiles are awkward for agents to reason about directly. The dominant problems are:

- the default workflow opens a browser UI and local symbol/source server
- the processed profile format is an index-heavy table graph rather than a simple list of samples
- cross-platform recording has OS-specific failure modes (Linux perf permissions, macOS code signing, Windows ETW/symbol servers)
- before/after analysis is easy for a human eyeballing the UI, but weakly structured for an agent

This bundle addresses those points with three narrow skills:

- `samply-recording` — create good local artifacts reliably
- `samply-hotspots` — summarize one profile into compact JSON/Markdown
- `samply-diffing` — compare two profiles with normalized percentages

## Suggested workflow

1. Use `samply-recording` to capture `baseline.profile.json.gz` and `candidate.profile.json.gz`.
2. Use `samply-hotspots` to summarize either profile when you need one-capture diagnosis.
3. Use `samply-diffing` to evaluate regressions or validate optimizations.

## Bundle layout

```text
skills/
  samply-recording/
  samply-hotspots/
  samply-diffing/
```

Each skill is self-contained and includes:

- `SKILL.md`
- `scripts/`
- `references/`
- `eval_queries.json`

## How to install

Copy one or more directories from `skills/` into the skills directory used by your agent client.

## Compatibility notes

- The Python scripts use only the standard library.
- `samply-recording` is designed to adapt to the installed `samply --help` output rather than assuming every flag exists.
- The bundle was written against samply's current browser-first / Firefox-processed-profile workflow and recent 0.13.x feature set.

## Maintenance tools

- `tools/check_sync.py` — verify (or `--write`) that the duplicated `profile_common.py` and `merge_syms.py` copies are byte-identical across skills. Run before commit.
- `tools/eval_runner.py` — score each skill's `eval_queries.json` against a Claude model. Set `ANTHROPIC_API_KEY` and run; pass `--dry-run` to validate eval/frontmatter shapes without calling the API. Useful when editing a skill description.
