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
            status = "ok" if value <= 1 else "warn"
            checks.append(
                {
                    "name": "perf_event_paranoid",
                    "status": status,
                    "value": value,
                    "message": (
                        "Kernel perf permissions look compatible with user-space profiling."
                        if status == "ok"
                        else "Kernel perf permissions may block non-root profiling."
                    ),
                    "suggestions": (
                        []
                        if status == "ok"
                        else [
                            "sudo sysctl kernel.perf_event_paranoid=1",
                            "If that still blocks profiling on this host, try: sudo sysctl kernel.perf_event_paranoid=-1",
                        ]
                    ),
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
            status = "ok" if value >= 1024 else "warn"
            checks.append(
                {
                    "name": "perf_event_mlock_kb",
                    "status": status,
                    "value": value,
                    "message": (
                        "Perf mlock limit looks reasonable."
                        if status == "ok"
                        else "Low perf mlock limit can trigger mmap/EPERM failures during profiling."
                    ),
                    "suggestions": (
                        []
                        if status == "ok"
                        else ["sudo sysctl kernel.perf_event_mlock_kb=2048"]
                    ),
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


def macos_checks(samply_path: Optional[str]) -> List[Dict[str, Any]]:
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
    result["samply"]["version_stdout"] = version["stdout"].strip() or version["stderr"].strip()

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
        result["checks"].extend(macos_checks(samply_path))
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
