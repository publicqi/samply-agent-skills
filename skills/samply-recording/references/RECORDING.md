# Recording with samply in agent workflows

Samply is excellent for interactive human analysis, but the default workflow is browser-first. Agents need file-first behavior.

## Why this skill exists

Samply's default `record` flow launches Firefox Profiler in a browser and serves symbols and source code from a local webserver. That is great for a human, but poor for a coding agent that needs deterministic local artifacts, compact summaries, and repeatable comparisons.

This skill therefore treats **saved profiles** as the primary output and the browser UI as optional.

## Platform notes

### Linux

Common blockers:

- `perf_event_paranoid` too restrictive
- `perf_event_mlock_kb` too small
- missing debug info / stripped binaries

Typical fixes:

```bash
sudo sysctl kernel.perf_event_paranoid=1
sudo sysctl kernel.perf_event_mlock_kb=2048
```

If that still fails, some systems require `CAP_PERFMON` or even `perf_event_paranoid=-1`.

Linux captures **on-CPU** samples only. Do not infer off-CPU wait stacks from a Linux profile.

### macOS

Samply cannot profile Apple-signed system binaries such as system `sleep` or system `python`. Profile your own binaries, Homebrew-installed binaries, or other unsigned/locally-signed binaries instead.

For attach mode, run:

```bash
samply setup
```

Repeat that after upgrading `samply`.

#### dSYM is required for usable Rust symbols on macOS

Even with `[profile.release] debug = 2` (or the recommended
`[profile.profiling]` recipe further down), Rust release builds on macOS
do not produce a `.dSYM` bundle. Without one, samply leaf symbol coverage
is typically 20-40% and inline frames are missing — the hotspot summary
will be full of `0x...` hex addresses.

Workflow:

```bash
# After every rebuild of the binary you intend to profile:
dsymutil ./target/profiling/<binary>

# Sanity-check that the dSYM matches the binary (UUIDs must be equal):
dwarfdump --uuid ./target/profiling/<binary>
dwarfdump --uuid ./target/profiling/<binary>.dSYM
```

If the UUIDs differ, the dSYM is stale (binary was rebuilt) — regenerate it.

Samply discovers the dSYM automatically when it is at the conventional
sibling path (`<binary>.dSYM/Contents/Resources/DWARF/<binary>`). If you
keep dSYMs elsewhere, pass `--symbol-dir <dir>`.

### Windows

Samply uses ETW and normally needs Administrator privileges while recording.

System-library and kernel symbols are usually poor unless you add Microsoft's symbol server:

```bash
samply record --windows-symbol-server https://msdl.microsoft.com/download/symbols ...
```

Recent samply versions also accept `--symbol-dir` for local binaries and `--windows-symbol-cache` for downloaded symbols.

## Symbol quality checklist

Before blaming the profiler, check symbol quality.

For Rust, prefer a profiling-style release build with debug info:

```toml
[profile.profiling]
inherits = "release"
debug = 2
split-debuginfo = "unpacked"  # macOS-friendly; lets dsymutil find object files
```

Then build with:

```bash
cargo build --profile profiling
```

On macOS, follow up with `dsymutil` (see "dSYM is required" above).

For C or C++, keep `-g`. For other compiled languages, preserve whatever debug information the platform's symbolication flow expects.

## Suggested command templates

### Launch a command

```bash
samply record --save-only -o build.profile.json.gz -- cargo build --profile profiling
```

### Run a benchmark

```bash
samply record --save-only -o bench.profile.json.gz -- ./target/profiling/my-benchmark
```

### Attach to a PID

```bash
samply record -p 12345 --save-only -o service.profile.json.gz
```

### Import perf/simpleperf

```bash
samply import perf.data
```

If available in the installed version, add:

- `--symbol-dir PATH`
- `--simpleperf-binary-cache PATH`
- `--unstable-presymbolicate`

## Reliability notes for agents

- Prefer one command per artifact.
- Prefer explicit output filenames.
- Preserve both before/after profiles for later diffing.
- `-d N` only bounds the sampling window; it does not force the child to
  exit. On samply 0.13.1 this affects both launched (`-- ./binary`) and
  attached (`-p PID`) modes. If your child is a long-running daemon, REPL,
  or event loop, samply will keep waiting for it after `-d` elapses, and
  the profile file will not be written. Stop the **child** with
  `kill -INT <child_pid>` once you have enough samples; samply finalizes
  and writes the profile shortly after.
- Do not use `pkill -f <pattern>` to stop the child if the pattern would
  also match the samply command line — it kills samply alongside, and the
  in-progress profile is lost. Match a unique substring of the child argv,
  or kill by PID.

## Symbols via `--unstable-presymbolicate`

`--unstable-presymbolicate` (samply 0.13.1) writes resolved symbols to a
sidecar file (`<profile>.syms.json`) **next to** the saved profile. The
samply-hotspots and samply-diffing skills auto-merge this sidecar at load
time, so you usually do not need to merge it yourself. If you need a
merged single-file profile (for tools that do not share the auto-merge):

```bash
scripts/merge_syms.py profile.json.gz
# writes profile.merged.json.gz
```
