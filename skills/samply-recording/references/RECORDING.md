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
debug = true
```

Then build with:

```bash
cargo build --profile profiling
```

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
- On samply 0.13.1, an open issue reports that `samply record -p ... --save-only -d 30` may not exit and write output as expected. For attached-process recordings, explicit stop control is safer than assuming `-d` will flush output.
