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

1. Run the preflight checker first. On macOS, pass the binary you intend to
   profile so the checker also verifies that a `.dSYM` bundle exists next to
   the binary and that its UUID matches:

```bash
scripts/check_env.py --mode all
scripts/check_env.py --mode all --binary ./target/profiling/your-binary  # macOS dSYM checks
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
   - Rust: use optimized builds **with debug info**. A reusable Cargo profile:
     ```toml
     [profile.profiling]
     inherits = "release"
     debug = 2
     split-debuginfo = "unpacked"  # macOS-friendly; lets dsymutil find object files
     ```
     Then `cargo build --profile profiling` and pass that binary to samply.
   - **macOS-specific**: Rust release builds do NOT auto-generate a `.dSYM`
     bundle. Without one, samply leaf coverage is often <40% and inline
     frames are missing. After every rebuild, regenerate the dSYM and verify
     the UUID matches:
     ```bash
     dsymutil ./target/profiling/<binary>
     dwarfdump --uuid ./target/profiling/<binary> ./target/profiling/<binary>.dSYM
     # both UUIDs must match; if they differ the dSYM is stale, regenerate.
     ```
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

`--unstable-presymbolicate` writes resolved symbols to a sidecar file
(`profile.json.syms.json`) **next to the profile**, not inside it. The
samply-hotspots and samply-diffing skills auto-merge this sidecar when they
load the profile. If you ever need a one-shot merged profile (for tools
that do not share the auto-merge), run:

```bash
../samply-hotspots/scripts/merge_syms.py profile.json.gz
# writes profile.merged.json.gz
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
- `-d N` only bounds the sampling window; it does NOT force the child to
  exit. For long-running daemons / REPLs / event loops in either launched
  (`-- ./binary`) or attached (`-p PID`) mode on samply 0.13.1, samply will
  keep waiting for the child after `-d` elapses. Stop the **child** with an
  explicit `kill -INT <child_pid>` once you have enough samples — samply
  then finalizes and writes the profile.
- Never use `pkill -f <pattern>` to stop a samply child if the pattern
  matches the samply command line too — it kills samply alongside the child
  and the in-progress profile is lost. Match a unique substring of the
  child's argv, or kill by PID.

# Failure handling

If the command fails, inspect the preflight output and then consult:

- `references/RECORDING.md`

Common causes:
- Linux `perf_event_paranoid` or `perf_event_mlock_kb`
- macOS trying to profile Apple-signed system binaries
- macOS attach without `samply setup`
- macOS Rust binary missing a `.dSYM` bundle (run `dsymutil`; verify UUID match)
- macOS dSYM stale after rebuild (UUID mismatch — regenerate)
- Windows recording without Administrator privileges
- Poor symbols because the binary was stripped or debug info was omitted
- Profile finalize never wrote because the long-running child never exited
  (samply waits for child exit after `-d` elapses) — send SIGINT to the
  child PID, not to samply, and not via `pkill -f`.

# Output contract

The artifact you want is a local profile file such as `profile.json` or `profile.json.gz`. Once it exists, use the hotspot or diffing skills rather than trying to interpret the browser UI.
