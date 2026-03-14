---
name: samply-recording
description: Use this skill when the user wants to profile a command, benchmark, build, test, service, PID, perf.data file, or Android simpleperf capture with samply, even if they only say “profile it”, “record a flame graph”, “capture hotspots”, or “use Firefox Profiler”. It converts samply into a headless, agent-friendly workflow: preflight environment checks, symbol/debug-info setup, non-interactive --save-only recording, and OS-specific fixes for Linux perf permissions, macOS code signing, and Windows ETW/symbol servers.
license: Apache-2.0
metadata:
  author: OpenAI
  version: "1.0.0"
---

# Goal

Produce a local profile artifact that another agent or skill can analyze without opening a browser and without relying on a human to inspect Firefox Profiler interactively.

# Default procedure

1. Run the preflight checker first.

```bash
scripts/check_env.py --mode all
```

2. Prefer recording to a file with `--save-only` and an explicit output path, for example:

```bash
samply record --save-only -o profile.json.gz -- ./your-command arg1 arg2
```

3. Prefer launched-command profiling over PID attach when both are viable. Launching usually captures startup work more reliably and avoids attach-specific platform friction.

4. Use stable, explicit filenames that preserve comparison order, for example:
   - `baseline.profile.json.gz`
   - `candidate.profile.json.gz`
   - `build.profile.json.gz`
   - `test.profile.json.gz`

5. Preserve symbol quality before recording:
   - Rust: use optimized builds **with debug info**
   - C/C++: keep `-g`
   - Windows: add `--windows-symbol-server https://msdl.microsoft.com/download/symbols` when system symbols matter
   - If local binaries or PDBs live outside default search paths, add `--symbol-dir PATH`

6. Only after a profile artifact exists should you move on to summary or diffing.

# Recording patterns

## Launch a command

```bash
samply record --save-only -o profile.json.gz -- ./binary arg1 arg2
```

If supported by the installed version and symbol quality matters, prefer presymbolication:

```bash
samply record --unstable-presymbolicate --save-only -o profile.json.gz -- ./binary arg1 arg2
```

## Attach to a running process

```bash
samply record -p <PID> --save-only -o attached.profile.json.gz
```

On macOS, run `samply setup` first if attach fails.

## Import existing profiler data

For `perf.data` or Android `simpleperf` captures:

```bash
samply import perf.data
```

If the installed version supports extra symbol locations or binary caches, add them explicitly when needed.

# Decision rules

Prefer these defaults unless the task clearly calls for something else:

- Use `--save-only` instead of opening the Firefox Profiler UI.
- Use `.json.gz` output to reduce artifact size.
- Keep one profile per run. Do not overwrite a baseline if you expect to compare later.
- Use `--main-thread-only` only when the user explicitly wants lower overhead or only the main thread matters.
- Use `--include-args` when command-line arguments are part of the diagnosis and the installed version supports it.
- Do not claim Linux off-CPU visibility; Linux captures on-CPU samples only.
- If attach duration is needed on samply 0.13.1, do not rely on `-d` alone for a clean stop on attached processes; drive termination explicitly if necessary.

# Failure handling

If the command fails, inspect the preflight output and then consult:

- `references/RECORDING.md`

Common causes:
- Linux `perf_event_paranoid` or `perf_event_mlock_kb`
- macOS trying to profile Apple-signed system binaries
- macOS attach without `samply setup`
- Windows recording without Administrator privileges
- Poor symbols because the binary was stripped or debug info was omitted

# Output contract

The artifact you want is a local profile file such as `profile.json` or `profile.json.gz`. Once it exists, use the hotspot or diffing skills rather than trying to interpret the browser UI.
