#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


FLAG_RE = re.compile(r"(?<![\w-])(--[a-zA-Z0-9][a-zA-Z0-9-]*)")
SHORT_FLAG_RE = re.compile(r"(?<![\w-])(-[A-Za-z])(?![\w-])")
VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")

MIN_SAMPLY_VERSION: tuple[int, int, int] = (0, 13, 0)


def run(cmd: List[str]) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": f"command not found: {cmd[0]}"}
    except Exception as exc:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(exc)}

    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def parse_samply_version(version_text: str) -> Optional[tuple[int, int, int]]:
    """Pull a semver triple out of `samply --version` output.

    Tolerates both `samply 0.13.1` and bare `0.13.1`; returns None if no
    triple can be found (e.g. unexpected stub or build metadata only).
    """
    match = VERSION_RE.search(version_text or "")
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def version_check(version_text: str) -> Dict[str, Any]:
    parsed = parse_samply_version(version_text)
    if parsed is None:
        return {
            "name": "samply_version",
            "status": "warn",
            "value": version_text,
            "message": (
                "Could not parse samply version; the bundle assumes "
                f"samply >= {'.'.join(str(v) for v in MIN_SAMPLY_VERSION)}."
            ),
            "suggestions": ["Upgrade samply: cargo install samply --locked"],
        }
    status = "ok" if parsed >= MIN_SAMPLY_VERSION else "fail"
    pretty = ".".join(str(v) for v in parsed)
    minimum = ".".join(str(v) for v in MIN_SAMPLY_VERSION)
    return {
        "name": "samply_version",
        "status": status,
        "value": pretty,
        "message": (
            f"samply {pretty} satisfies the >= {minimum} minimum."
            if status == "ok"
            else f"samply {pretty} is older than the >= {minimum} minimum; "
            "expect missing flags such as --unstable-presymbolicate."
        ),
        "suggestions": (
            []
            if status == "ok"
            else ["Upgrade samply: cargo install samply --locked"]
        ),
    }


def parse_flags(help_text: str) -> Dict[str, List[str]]:
    long_flags = sorted(set(FLAG_RE.findall(help_text)))
    short_flags = sorted(set(SHORT_FLAG_RE.findall(help_text)))
    return {"long": long_flags, "short": short_flags}


def read_text(path: str) -> Optional[str]:
    try:
        return Path(path).read_text().strip()
    except Exception:
        return None


def linux_checks() -> List[Dict[str, Any]]:
    checks = []

    paranoid = read_text("/proc/sys/kernel/perf_event_paranoid")
    if paranoid is not None:
        try:
            value = int(paranoid)
            # Three tiers, because "warn" alone gets ignored by agents who
            # then waste a recording on a profile full of `[unknown]` stacks:
            #   <= 1  permits user-space sampling with kernel-side context
            #   == 2  user-space-only (default on most distros; usually fine
            #         for own processes but kernel symbols are restricted)
            #   >= 3  blocks non-root user-space profiling outright
            #         (Ubuntu 24.04 ships 4 by default)
            if value <= 1:
                status = "ok"
                message = "Kernel perf permissions look compatible with user-space profiling."
                suggestions: List[str] = []
            elif value == 2:
                status = "warn"
                message = (
                    "perf_event_paranoid=2 limits sampling to user-space events. "
                    "Profiling your own processes works, but kernel/syscall frames "
                    "will be missing."
                )
                suggestions = [
                    "Lower it if you need kernel frames: sudo sysctl kernel.perf_event_paranoid=1",
                ]
            else:
                status = "fail"
                message = (
                    f"perf_event_paranoid={value} blocks non-root user-space "
                    "profiling. samply will record but stacks come back empty or "
                    "unsymbolicated. This is the default on Ubuntu 24.04+."
                )
                suggestions = [
                    "sudo sysctl kernel.perf_event_paranoid=1",
                    "If that still blocks profiling on this host, try: sudo sysctl kernel.perf_event_paranoid=-1",
                    "Persist across reboots: echo 'kernel.perf_event_paranoid=1' | sudo tee /etc/sysctl.d/99-perf.conf",
                ]
            checks.append(
                {
                    "name": "perf_event_paranoid",
                    "status": status,
                    "value": value,
                    "message": message,
                    "suggestions": suggestions,
                }
            )
        except ValueError:
            checks.append(
                {
                    "name": "perf_event_paranoid",
                    "status": "warn",
                    "value": paranoid,
                    "message": "Could not parse kernel perf permissions value.",
                    "suggestions": [],
                }
            )

    mlock = read_text("/proc/sys/kernel/perf_event_mlock_kb")
    if mlock is not None:
        try:
            value = int(mlock)
            if value >= 1024:
                status = "ok"
                message = "Perf mlock limit looks reasonable."
                suggestions = []
            elif value >= 512:
                status = "warn"
                message = (
                    f"Perf mlock limit ({value} KB) is on the low side; "
                    "sustained profiling can hit mmap/EPERM failures."
                )
                suggestions = ["sudo sysctl kernel.perf_event_mlock_kb=2048"]
            else:
                status = "fail"
                message = (
                    f"Perf mlock limit ({value} KB) is too low; samply will "
                    "almost certainly hit mmap/EPERM and produce empty profiles."
                )
                suggestions = ["sudo sysctl kernel.perf_event_mlock_kb=2048"]
            checks.append(
                {
                    "name": "perf_event_mlock_kb",
                    "status": status,
                    "value": value,
                    "message": message,
                    "suggestions": suggestions,
                }
            )
        except ValueError:
            checks.append(
                {
                    "name": "perf_event_mlock_kb",
                    "status": "warn",
                    "value": mlock,
                    "message": "Could not parse kernel perf mlock value.",
                    "suggestions": [],
                }
            )

    return checks


_DWARFDUMP_UUID_RE = re.compile(r"UUID:\s*([0-9A-Fa-f-]+)")


def _read_uuid(path: str) -> Optional[str]:
    if not shutil.which("dwarfdump"):
        return None
    result = run(["dwarfdump", "--uuid", path])
    if result["returncode"] != 0:
        return None
    match = _DWARFDUMP_UUID_RE.search(result["stdout"] or "")
    return match.group(1).upper() if match else None


def macos_dsym_checks(binary: str) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []

    if not os.path.exists(binary):
        checks.append(
            {
                "name": "binary_path",
                "status": "warn",
                "value": binary,
                "message": "Binary not found at the given path; skipping dSYM checks.",
                "suggestions": [
                    "Build the binary first, e.g. `cargo build --profile profiling`.",
                ],
            }
        )
        return checks

    dsym_path = binary + ".dSYM"
    dsym_exists = os.path.isdir(dsym_path)
    checks.append(
        {
            "name": "dsym_present",
            "status": "ok" if dsym_exists else "warn",
            "value": dsym_path,
            "message": (
                f"dSYM bundle found next to binary: {dsym_path}"
                if dsym_exists
                else "macOS Rust release builds do not auto-generate a .dSYM. "
                "Without it, samply leaf coverage is often <40% and inline frames are missing."
            ),
            "suggestions": (
                []
                if dsym_exists
                else [f"Run: dsymutil {binary}"]
            ),
        }
    )

    if dsym_exists:
        binary_uuid = _read_uuid(binary)
        dsym_uuid = _read_uuid(dsym_path)
        if binary_uuid and dsym_uuid:
            match = binary_uuid == dsym_uuid
            checks.append(
                {
                    "name": "dsym_uuid_match",
                    "status": "ok" if match else "warn",
                    "value": {"binary": binary_uuid, "dsym": dsym_uuid},
                    "message": (
                        "Binary and dSYM UUIDs match."
                        if match
                        else "dSYM is stale; UUIDs differ from the binary. "
                        "Symbolication will be silently wrong."
                    ),
                    "suggestions": (
                        []
                        if match
                        else [
                            f"Regenerate: rm -rf {dsym_path} && dsymutil {binary}",
                        ]
                    ),
                }
            )

    return checks


def macos_checks(samply_path: Optional[str], binary: Optional[str] = None) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    if samply_path and shutil.which("codesign"):
        result = run(["codesign", "-dv", samply_path])
        checks.append(
            {
                "name": "codesign_metadata",
                "status": "ok" if result["returncode"] == 0 else "warn",
                "message": (
                    "codesign returned metadata for the samply binary."
                    if result["returncode"] == 0
                    else "Could not read codesign metadata for the samply binary."
                ),
                "suggestions": (
                    []
                    if result["returncode"] == 0
                    else ["Run `samply setup` before attaching to running processes."]
                ),
            }
        )

    dsymutil_path = shutil.which("dsymutil")
    checks.append(
        {
            "name": "dsymutil_available",
            "status": "ok" if dsymutil_path else "warn",
            "value": dsymutil_path,
            "message": (
                "dsymutil is on PATH; you can generate .dSYM bundles for Rust/C++ binaries."
                if dsymutil_path
                else "dsymutil not found on PATH. Without it samply will only see "
                "raw addresses for binaries that do not ship inline DWARF."
            ),
            "suggestions": (
                []
                if dsymutil_path
                else [
                    "Install Xcode Command Line Tools: `xcode-select --install`",
                    "Or `brew install llvm` (provides dsymutil under the llvm prefix).",
                ]
            ),
        }
    )

    checks.append(
        {
            "name": "system_binary_limitation",
            "status": "warn",
            "message": (
                "Profiling Apple-signed system binaries can fail because they block "
                "DYLD_INSERT_LIBRARIES."
            ),
            "suggestions": [
                "Prefer profiling binaries you built yourself, unsigned binaries, or locally signed binaries.",
                "Run `samply setup` after each samply update if you need to attach to running processes.",
            ],
        }
    )

    if binary:
        checks.extend(macos_dsym_checks(binary))

    return checks


def windows_is_admin() -> Optional[bool]:
    try:
        import ctypes  # type: ignore

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return None


def windows_checks() -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    admin = windows_is_admin()
    if admin is not None:
        checks.append(
            {
                "name": "administrator_privileges",
                "status": "ok" if admin else "warn",
                "value": admin,
                "message": (
                    "Administrator privileges are available."
                    if admin
                    else "Windows recording usually needs Administrator privileges because samply uses ETW/xperf."
                ),
                "suggestions": (
                    []
                    if admin
                    else ["Re-run the shell as Administrator before using `samply record` on Windows."]
                ),
            }
        )

    checks.append(
        {
            "name": "symbol_servers",
            "status": "warn",
            "message": "Windows system libraries are often unsymbolicated unless you configure a symbol server.",
            "suggestions": [
                "Add: --windows-symbol-server https://msdl.microsoft.com/download/symbols",
            ],
        }
    )
    return checks


def build_recommended_commands(
    record_flags: Dict[str, List[str]],
    import_flags: Dict[str, List[str]],
    system_name: str,
) -> Dict[str, str]:
    record_long = set(record_flags.get("long", []))
    record_short = set(record_flags.get("short", []))

    save_bits = []
    if "--save-only" in record_long:
        save_bits.append("--save-only")
    if "-o" in record_short:
        save_bits.extend(["-o", "profile.json.gz"])

    presym = None
    if "--unstable-presymbolicate" in record_long:
        presym = "--unstable-presymbolicate"
    elif "--presymbolicate" in record_long:
        presym = "--presymbolicate"

    record_launch = ["samply", "record"]
    record_attach = ["samply", "record"]

    if presym:
        record_launch.append(presym)

    record_launch.extend(save_bits)
    record_launch.extend(["--", "your-command", "arg1", "arg2"])

    record_attach.extend(["-p", "<PID>"])
    if presym:
        record_attach.append(presym)
    record_attach.extend(save_bits)

    if system_name == "Windows" and "--windows-symbol-server" in record_long:
        record_launch.extend(["--windows-symbol-server", "https://msdl.microsoft.com/download/symbols"])

    out = {
        "record_launch": " ".join(record_launch),
        "record_attach": " ".join(record_attach),
    }

    if import_flags.get("long") or import_flags.get("short"):
        out["import_perf"] = "samply import perf.data"
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect the local environment and samply CLI support for agent-friendly profiling."
    )
    parser.add_argument(
        "--mode",
        choices=("record", "attach", "import", "all"),
        default="all",
        help="Intended workflow. Affects some suggestions. Default: all",
    )
    parser.add_argument(
        "--binary",
        default=None,
        help=(
            "Optional path to the binary you plan to profile. On macOS this "
            "enables dSYM presence and UUID-match checks (binary vs "
            "binary.dSYM)."
        ),
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="Indentation to use for JSON output. Default: 2",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    system_name = platform.system() or "Unknown"
    samply_path = shutil.which("samply")

    result: Dict[str, Any] = {
        "platform": {
            "system": system_name,
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "samply": {
            "path": samply_path,
            "found": bool(samply_path),
        },
        "checks": [],
        "recommended_commands": {},
        "notes": [],
    }

    if not samply_path:
        result["notes"].append("Install samply before using these skills.")
        json.dump(result, sys.stdout, indent=args.indent)
        sys.stdout.write("\n")
        return 0

    version = run(["samply", "--version"])
    version_text = version["stdout"].strip() or version["stderr"].strip()
    result["samply"]["version_stdout"] = version_text
    parsed_version = parse_samply_version(version_text)
    result["samply"]["version_parsed"] = (
        ".".join(str(v) for v in parsed_version) if parsed_version else None
    )
    result["checks"].append(version_check(version_text))

    record_help = run(["samply", "record", "--help"])
    import_help = run(["samply", "import", "--help"])
    setup_help = run(["samply", "setup", "--help"])

    record_flags = parse_flags((record_help["stdout"] or "") + "\n" + (record_help["stderr"] or ""))
    import_flags = parse_flags((import_help["stdout"] or "") + "\n" + (import_help["stderr"] or ""))

    result["samply"]["record_flags"] = record_flags
    if import_help["returncode"] is not None:
        result["samply"]["import_flags"] = import_flags
    result["samply"]["setup_supported"] = setup_help["returncode"] == 0 or "setup" in ((setup_help["stdout"] or "") + (setup_help["stderr"] or ""))

    if system_name == "Linux":
        result["checks"].extend(linux_checks())
    elif system_name == "Darwin":
        result["checks"].extend(macos_checks(samply_path, args.binary))
    elif system_name == "Windows":
        result["checks"].extend(windows_checks())

    result["recommended_commands"] = build_recommended_commands(
        record_flags, import_flags, system_name
    )

    if "--include-args" in record_flags.get("long", []):
        result["notes"].append("`--include-args` is available if you want command-line arguments captured in the profile.")
    if "--main-thread-only" in record_flags.get("long", []):
        result["notes"].append("`--main-thread-only` is available when you need lower-overhead sampling.")
    if "--symbol-dir" in record_flags.get("long", []):
        result["notes"].append("Use `--symbol-dir` to point samply at local debug symbols when source / function names are missing.")
    if "--unstable-presymbolicate" in record_flags.get("long", []):
        result["notes"].append("This build supports `--unstable-presymbolicate`, which is usually the most agent-friendly way to get resolved names into saved profiles.")
    elif "--presymbolicate" in record_flags.get("long", []):
        result["notes"].append("This build supports `--presymbolicate`, which is usually the most agent-friendly way to get resolved names into saved profiles.")

    json.dump(result, sys.stdout, indent=args.indent)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
