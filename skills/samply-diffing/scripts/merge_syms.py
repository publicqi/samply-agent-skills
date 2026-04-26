#!/usr/bin/env python3
"""
Merge a samply `--unstable-presymbolicate` sidecar (`*.syms.json`) into the
processed profile, replacing hex-address `funcTable.name` strings with resolved
symbols.

Usage:
    merge_syms.py <profile.json[.gz]> [<sidecar.syms.json>] [<output.json[.gz]>]

If the sidecar path is omitted, it is auto-discovered by stripping a trailing
`.gz` from the profile path and appending `.syms.json` (the layout samply
writes by default).

If the output path is omitted, the merged profile is written next to the input
as `<stem>.merged.json.gz` (preserving gzip if the input was gzipped).

This script is also importable: `merge_syms_into(profile_dict, sidecar_dict)`
mutates the profile in place and returns `(resolved, total_funcs)`.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _normalize_debug_id(s: str) -> str:
    """Strip dashes, lowercase. Tolerates samply's age-byte suffix."""
    return s.replace("-", "").lower()


def _build_addr_lookup(
    lib_data: Dict[str, Any], sym_strings: List[str]
) -> Dict[int, str]:
    """Build observation_rva -> resolved_symbol for one lib's sidecar entry.

    Uses `known_addresses` (which maps observed RVAs to symbol_table indices)
    plus a coarse rva-range fallback for addresses we did not see during
    sampling but which still appear in the profile's frameTable.
    """
    out: Dict[int, str] = {}
    sym_table = lib_data.get("symbol_table") or []
    known = lib_data.get("known_addresses") or []
    for entry in known:
        if not entry or len(entry) < 2:
            continue
        rva, sym_idx = entry[0], entry[1]
        sym = sym_table[sym_idx] if 0 <= sym_idx < len(sym_table) else None
        if not sym:
            continue
        name_idx = sym.get("symbol")
        if name_idx is None or name_idx >= len(sym_strings):
            continue
        out[int(rva)] = sym_strings[name_idx]
    # Fallback: also map the start of every symbol_table entry, in case the
    # profile references an exact start address that did not appear in
    # known_addresses.
    for sym in sym_table:
        rva = sym.get("rva")
        name_idx = sym.get("symbol")
        if rva is None or name_idx is None or name_idx >= len(sym_strings):
            continue
        out.setdefault(int(rva), sym_strings[name_idx])
    return out


def _addr_lookups_by_lib(
    profile: Dict[str, Any], sidecar: Dict[str, Any]
) -> Dict[int, Dict[int, str]]:
    """Map profile lib_index -> (address -> symbol_name) using debug_id match."""
    sym_strings = sidecar.get("string_table") or []
    by_debug_id: Dict[str, Dict[str, Any]] = {}
    for entry in sidecar.get("data") or []:
        if not isinstance(entry, dict):
            continue
        did = entry.get("debug_id")
        if not did:
            continue
        by_debug_id[_normalize_debug_id(did)] = entry

    out: Dict[int, Dict[int, str]] = {}
    for lib_idx, lib in enumerate(profile.get("libs") or []):
        bid = lib.get("breakpadId") or lib.get("debugId")
        if not bid:
            continue
        entry = by_debug_id.get(_normalize_debug_id(bid))
        if entry is None:
            # Some samply versions append an "age" byte to breakpadId; retry
            # against the leading 32 hex chars.
            entry = by_debug_id.get(_normalize_debug_id(bid)[:32])
        if entry is None:
            continue
        out[lib_idx] = _build_addr_lookup(entry, sym_strings)
    return out


def merge_syms_into(
    profile: Dict[str, Any], sidecar: Dict[str, Any]
) -> Tuple[int, int]:
    """Rewrite hex `funcTable.name` strings in-place. Returns (resolved, total)."""
    addr_by_lib = _addr_lookups_by_lib(profile, sidecar)
    if not addr_by_lib:
        return (0, 0)

    total_funcs = 0
    resolved = 0

    for thread in profile.get("threads") or []:
        string_array = thread.get("stringArray")
        if string_array is None:
            string_array = thread.get("stringTable")
            if string_array is None:
                continue
            # Some processed-profile flavors store stringTable as an object;
            # only handle the list-shaped case here.
            if not isinstance(string_array, list):
                continue
        func_table = thread.get("funcTable") or {}
        frame_table = thread.get("frameTable") or {}
        resource_table = thread.get("resourceTable") or {}
        func_resources = func_table.get("resource") or []
        func_names = func_table.get("name") or []
        frame_funcs = frame_table.get("func") or []
        frame_addresses = frame_table.get("address") or []
        resource_libs = resource_table.get("lib") or []

        # func_idx -> lib_idx (via resourceTable)
        func_lib: Dict[int, Optional[int]] = {}
        for func_idx, res_idx in enumerate(func_resources):
            if res_idx is None or res_idx < 0 or res_idx >= len(resource_libs):
                func_lib[func_idx] = None
            else:
                func_lib[func_idx] = resource_libs[res_idx]

        # func_idx -> address (pick the first frame referencing this func)
        func_addr: Dict[int, int] = {}
        for f_idx, fn_idx in enumerate(frame_funcs):
            if fn_idx in func_addr:
                continue
            if fn_idx is None or fn_idx < 0 or fn_idx >= len(func_names):
                continue
            addr = frame_addresses[f_idx] if f_idx < len(frame_addresses) else None
            if isinstance(addr, int) and addr >= 0:
                func_addr[fn_idx] = int(addr)

        for func_idx, name_idx in enumerate(func_names):
            total_funcs += 1
            if name_idx is None or name_idx < 0 or name_idx >= len(string_array):
                continue
            current = string_array[name_idx]
            if not isinstance(current, str) or not current.startswith("0x"):
                continue
            lib_idx = func_lib.get(func_idx)
            if lib_idx is None:
                continue
            lookup = addr_by_lib.get(lib_idx)
            if not lookup:
                continue
            addr = func_addr.get(func_idx)
            if addr is None:
                continue
            sym = lookup.get(addr)
            if sym is None:
                continue
            string_array[name_idx] = sym
            resolved += 1

    return (resolved, total_funcs)


def _read_json(path: Path) -> Any:
    with path.open("rb") as f:
        raw = f.read()
    if raw[:2] == b"\x1f\x8b" or path.suffix == ".gz":
        return json.loads(gzip.decompress(raw).decode("utf-8"))
    return json.loads(raw.decode("utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    if path.suffix == ".gz":
        with gzip.open(path, "wb") as f:
            f.write(data)
    else:
        path.write_bytes(data)


def discover_sidecar(profile_path: Path) -> Optional[Path]:
    """Return the conventional sidecar path next to the profile, if it exists."""
    stem = profile_path
    if stem.suffix == ".gz":
        stem = stem.with_suffix("")
    candidate = stem.with_suffix(stem.suffix + ".syms.json")
    return candidate if candidate.exists() else None


def main(argv: List[str]) -> int:
    if len(argv) < 2 or len(argv) > 4:
        print(__doc__, file=sys.stderr)
        return 2

    profile_path = Path(argv[1])
    sidecar_path: Optional[Path]
    if len(argv) >= 3:
        sidecar_path = Path(argv[2])
    else:
        sidecar_path = discover_sidecar(profile_path)
        if sidecar_path is None:
            print(
                f"No sidecar found next to {profile_path}; expected "
                f"{profile_path.with_suffix('').with_suffix('.syms.json').name} or similar.",
                file=sys.stderr,
            )
            return 2

    if len(argv) == 4:
        output_path = Path(argv[3])
    else:
        stem = profile_path
        if stem.suffix == ".gz":
            stem = stem.with_suffix("")
        if stem.suffix == ".json":
            stem = stem.with_suffix("")
        output_path = stem.with_name(stem.name + ".merged.json.gz")

    profile = _read_json(profile_path)
    sidecar = _read_json(sidecar_path)
    resolved, total = merge_syms_into(profile, sidecar)
    _write_json(output_path, profile)
    print(
        f"resolved {resolved}/{total} funcs; wrote {output_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
