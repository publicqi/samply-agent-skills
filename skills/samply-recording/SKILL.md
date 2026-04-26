---
name: samply-recording
description: Use this skill when the user wants to profile a command, benchmark, build, test, service, PID, perf.data file, or Android simpleperf capture with samply, even if they only say “profile it”, “record a flame graph”, “capture hotspots”, or “use Firefox Profiler”. It converts samply into a headless, agent-friendly workflow: preflight environment checks, symbol/debug-info setup, non-interactive --save-only recording, and OS-specific fixes for Linux perf permissions, macOS code signing, and Windows ETW/symbol servers.
---

# Goal

Produce a local profile artifact that another agent or skill can analyze without opening a browser and without relying on a human to inspect Firefox Profiler interactively.

# Default procedure

1. Run the preflight checker. On macOS, pass the binary so it also checks the `.dSYM` bundle:

   ```bash
   scripts/check_env.py --mode all
   scripts/check_env.py --mode all --binary ./target/profiling/your-binary
   ```

   Treat any check with `"status": "fail"` as a blocker — apply its `suggestions` before recording. Recording with a failing preflight (for example, `perf_event_paranoid >= 3` on Ubuntu 24.04+) usually produces a profile with empty or `[unknown]` stacks, and the run has to be redone.

2. Record to a file with `--save-only` and an explicit output path:

   ```bash
   samply record --save-only -o profile.json.gz -- ./your-command arg1 arg2
   ```

   Prefer launching a command over attaching to a PID when both are viable.

   For long-running children (daemons, REPLs, event loops) use the wrapper instead — it handles `--save-only`, output naming, presymbolicate detection, and the SIGINT-on-child handoff that lets samply finalize:

   ```bash
   scripts/record_profile.py -o profile.json.gz --max-duration 30 -- ./your-server
   scripts/record_profile.py --pid 12345 --max-duration 10
   ```

3. Use stable filenames that preserve comparison order: `baseline.profile.json.gz`, `candidate.profile.json.gz`, `build.profile.json.gz`.

4. Preserve symbol quality before recording. The full per-platform recipe (Cargo profile for Rust, `dsymutil` + UUID verification for macOS, `--symbol-dir` and Windows symbol servers) lives in `references/RECORDING.md` — read it before the first capture on a new platform.

5. Only after a profile artifact exists should you move on to summary or diffing.

# Recording patterns

```bash
# Launch a command
samply record --save-only -o profile.json.gz -- ./binary arg1 arg2

# Attach to a running process (run `samply setup` first on macOS if attach fails)
samply record -p <PID> --save-only -o attached.profile.json.gz

# Import perf.data or Android simpleperf
samply import perf.data
```

If the installed version exposes `--unstable-presymbolicate`, prefer it — it writes a `<profile>.syms.json` sidecar that the hotspots / diffing skills auto-merge. Details in `references/RECORDING.md`.

# Decision rules

- Use `--save-only` instead of opening the Firefox Profiler UI.
- Use `.json.gz` output to reduce artifact size.
- Keep one profile per run. Do not overwrite a baseline you may compare against later.
- Use `--main-thread-only` only when overhead or scope demands it.
- Use `--include-args` when command-line arguments are part of the diagnosis.
- Linux captures on-CPU samples only. Do not claim off-CPU visibility from a Linux profile.
- `-d N` bounds the sampling window but does **not** force the child to exit. For long-running children, send SIGINT to the **child** PID; samply then finalizes and writes the profile. Never `pkill -f <pattern>` if the pattern matches samply's own argv. See `references/RECORDING.md` for the full caveat.

# Failure handling

If recording fails, read the preflight output first, then `references/RECORDING.md`. Common causes: Linux `perf_event_paranoid` / `perf_event_mlock_kb`, macOS Apple-signed system binaries, macOS attach without `samply setup`, macOS missing or stale `.dSYM`, Windows without Administrator, stripped binaries, or a long-running child that never exited.

# Output contract

A local file such as `profile.json` or `profile.json.gz`. Once it exists, hand off to the hotspots or diffing skill rather than interpreting the browser UI.
