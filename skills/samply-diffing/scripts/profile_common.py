#!/usr/bin/env python3
"""
Shared helpers for analyzing Firefox processed profiles produced by samply.

This module intentionally supports both:
- processed profile tables (columnar arrays + length)
- source-style tables (schema + data rows)

The output structures are optimized for deterministic machine consumption.
"""

from __future__ import annotations

import gzip
import io
import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

HEXISH_RE = re.compile(r"^(?:0x)?[0-9a-fA-F]{6,}$")
UNKNOWN_NAMES = {
    "",
    "?",
    "??",
    "<unknown>",
    "(root)",
}


def _decode_profile_bytes(raw: bytes, is_gz: bool) -> Dict[str, Any]:
    if is_gz:
        return json.loads(gzip.decompress(raw).decode("utf-8"))
    return json.loads(raw.decode("utf-8"))


def _try_auto_merge_sidecar(profile: Dict[str, Any], profile_path: Path) -> None:
    """Auto-merge a sibling samply `--unstable-presymbolicate` sidecar.

    Side-effect only; failures are silent so this stays a strict optimization.
    """
    try:
        from merge_syms import discover_sidecar, merge_syms_into  # type: ignore
    except Exception:
        return
    sidecar_path = discover_sidecar(profile_path)
    if sidecar_path is None:
        return
    try:
        with sidecar_path.open("rb") as f:
            sidecar = json.loads(f.read().decode("utf-8"))
        merge_syms_into(profile, sidecar)
    except Exception:
        pass


def load_profile(path: str) -> Dict[str, Any]:
    if path == "-":
        raw = os.read(0, 1 << 30)
        return _decode_profile_bytes(raw, raw[:2] == b"\x1f\x8b")

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Profile not found: {path}")

    with p.open("rb") as f:
        raw = f.read()

    profile = _decode_profile_bytes(raw, raw[:2] == b"\x1f\x8b" or p.suffix == ".gz")
    _try_auto_merge_sidecar(profile, p)
    return profile


def get_meta(profile: Dict[str, Any]) -> Dict[str, Any]:
    return profile.get("meta") or {}


def iter_profile_nodes(profile: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    yield profile
    for child in profile.get("processes", []) or []:
        if isinstance(child, dict):
            yield from iter_profile_nodes(child)


def iter_threads(profile: Dict[str, Any]) -> Iterator[Tuple[Dict[str, Any], Dict[str, Any]]]:
    for node in iter_profile_nodes(profile):
        for thread in node.get("threads", []) or []:
            if isinstance(thread, dict):
                yield thread, node


def normalize_table(table: Any) -> Dict[str, List[Any]]:
    """
    Normalize a table into columnar dict-of-lists form.

    Supports:
    - {"schema": {"col": 0, ...}, "data": [[...], ...]}
    - {"col": [...], "other": [...], "length": N}
    """
    if not isinstance(table, dict):
        return {}

    if "schema" in table and "data" in table:
        schema = table.get("schema") or {}
        rows = table.get("data") or []
        columns: Dict[str, List[Any]] = {name: [] for name in schema}
        for row in rows:
            for name, idx in schema.items():
                if isinstance(row, list) and idx < len(row):
                    columns[name].append(row[idx])
                else:
                    columns[name].append(None)
        columns["length"] = [len(rows)]
        return columns

    columns = {}
    max_len = 0
    for key, value in table.items():
        if key == "length":
            continue
        if isinstance(value, list):
            columns[key] = value
            max_len = max(max_len, len(value))
    if "length" not in columns:
        columns["length"] = [table.get("length", max_len)]
    return columns


def table_len(table: Dict[str, List[Any]]) -> int:
    val = table.get("length", [0])
    if isinstance(val, list):
        return int(val[0]) if val else 0
    return int(val or 0)


def table_value(table: Dict[str, List[Any]], column: str, idx: int) -> Any:
    if idx is None or idx < 0:
        return None
    values = table.get(column)
    if not isinstance(values, list):
        return None
    if idx >= len(values):
        return None
    return values[idx]


def get_string(string_table: List[Any], idx_or_value: Any) -> Optional[str]:
    if idx_or_value is None:
        return None
    if isinstance(idx_or_value, str):
        return idx_or_value
    if isinstance(idx_or_value, (int, float)) and not isinstance(idx_or_value, bool):
        idx = int(idx_or_value)
        if idx < 0:
            return None
        if idx < len(string_table):
            value = string_table[idx]
            return value if isinstance(value, str) else str(value)
        return str(idx_or_value)
    return str(idx_or_value)


def likely_unsymbolicated(name: Optional[str]) -> bool:
    if name is None:
        return True
    stripped = name.strip()
    if stripped.lower() in UNKNOWN_NAMES:
        return True
    if HEXISH_RE.fullmatch(stripped):
        return True
    if stripped.startswith("0x") and len(stripped) >= 8:
        return True
    if stripped.startswith("0X") and len(stripped) >= 8:
        return True
    return False


def normalize_number(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        if math.isnan(value) or math.isinf(value):
            return default
        return float(value)
    try:
        out = float(value)
    except Exception:
        return default
    if math.isnan(out) or math.isinf(out):
        return default
    return out


def format_pct(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100.0, 4)


def safe_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return int(value)
    try:
        return int(str(value))
    except Exception:
        return None


def sort_counter_items(counter: Counter) -> List[Tuple[Any, float]]:
    return sorted(counter.items(), key=lambda item: (-item[1], str(item[0])))


def trim_counter(counter: Counter, limit: int) -> List[Tuple[Any, float]]:
    return sort_counter_items(counter)[: max(limit, 0)]


def resolve_resource_name(
    resource_table: Dict[str, List[Any]],
    resource_idx: Any,
    string_table: List[Any],
    libs: List[Dict[str, Any]],
) -> Optional[str]:
    idx = safe_int(resource_idx)
    if idx is None or idx < 0:
        return None

    name_idx = table_value(resource_table, "name", idx)
    name = get_string(string_table, name_idx)
    if name:
        return name

    lib_idx = safe_int(table_value(resource_table, "lib", idx))
    if lib_idx is not None and 0 <= lib_idx < len(libs):
        lib = libs[lib_idx]
        for key in ("debugName", "name", "path", "debugPath"):
            value = lib.get(key)
            if value:
                return str(value)

    return None


def format_function_display(frame: Dict[str, Any]) -> str:
    name = frame.get("name") or "<unknown>"
    resource = frame.get("resource")
    if resource and resource not in name:
        return f"{resource}!{name}"
    return str(name)


def stack_display(frames: List[Dict[str, Any]]) -> Tuple[str, ...]:
    return tuple(format_function_display(frame) for frame in frames if frame.get("name"))


def resolve_frame(
    frame_idx: int,
    string_table: List[Any],
    frame_table: Dict[str, List[Any]],
    func_table: Dict[str, List[Any]],
    resource_table: Dict[str, List[Any]],
    libs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    func_idx = safe_int(table_value(frame_table, "func", frame_idx))
    if func_idx is not None and func_idx >= 0:
        name = get_string(string_table, table_value(func_table, "name", func_idx))
        resource = resolve_resource_name(
            resource_table,
            table_value(func_table, "resource", func_idx),
            string_table,
            libs,
        )
        file_name = get_string(string_table, table_value(func_table, "fileName", func_idx))
        line = table_value(func_table, "lineNumber", func_idx)
        column = table_value(func_table, "columnNumber", func_idx)
        address = table_value(func_table, "address", func_idx)
        is_js = bool(table_value(func_table, "isJS", func_idx))
    else:
        location = table_value(frame_table, "location", frame_idx)
        name = get_string(string_table, location)
        resource = None
        file_name = None
        line = None
        column = None
        address = table_value(frame_table, "address", frame_idx)
        is_js = False

    if not name:
        name = f"<frame:{frame_idx}>"

    frame_line = table_value(frame_table, "line", frame_idx)
    frame_column = table_value(frame_table, "column", frame_idx)
    if line is None:
        line = frame_line
    if column is None:
        column = frame_column

    return {
        "name": name,
        "resource": resource,
        "file": get_string(string_table, file_name) if not isinstance(file_name, str) else file_name,
        "line": safe_int(line),
        "column": safe_int(column),
        "address": address,
        "is_js": bool(is_js),
    }


def analyze_thread(
    thread: Dict[str, Any],
    process_node: Dict[str, Any],
    profile_meta: Dict[str, Any],
) -> Dict[str, Any]:
    string_table = list(thread.get("stringArray") or thread.get("stringTable") or [])
    frame_table = normalize_table(thread.get("frameTable") or {})
    func_table = normalize_table(thread.get("funcTable") or {})
    stack_table = normalize_table(thread.get("stackTable") or {})
    resource_table = normalize_table(thread.get("resourceTable") or {})
    samples = normalize_table(thread.get("samples") or {})
    markers = normalize_table(thread.get("markers") or {})
    libs = list(thread.get("libs") or process_node.get("libs") or [])

    stack_cache: Dict[int, List[Dict[str, Any]]] = {}

    def get_stack_frames(stack_idx: Any) -> List[Dict[str, Any]]:
        idx = safe_int(stack_idx)
        if idx is None or idx < 0:
            return []
        if idx in stack_cache:
            return stack_cache[idx]

        frames: List[Dict[str, Any]] = []
        seen = set()
        current = idx
        while current is not None and current >= 0 and current not in seen:
            seen.add(current)
            frame_idx = safe_int(table_value(stack_table, "frame", current))
            if frame_idx is None or frame_idx < 0:
                break
            frames.append(
                resolve_frame(
                    frame_idx=frame_idx,
                    string_table=string_table,
                    frame_table=frame_table,
                    func_table=func_table,
                    resource_table=resource_table,
                    libs=libs,
                )
            )
            next_prefix = table_value(stack_table, "prefix", current)
            current = safe_int(next_prefix) if next_prefix is not None else None

        frames.reverse()
        stack_cache[idx] = frames
        return frames

    leaf_counter: Counter = Counter()
    inclusive_counter: Counter = Counter()
    stack_counter: Counter = Counter()
    function_details: Dict[str, Dict[str, Any]] = {}
    stack_details: Dict[Tuple[str, ...], List[Dict[str, Any]]] = {}
    marker_counter: Counter = Counter()

    weighted_samples = 0.0
    raw_samples = 0
    named_leaf_samples = 0.0
    min_time = None
    max_time = None

    sample_length = table_len(samples)
    for i in range(sample_length):
        stack_idx = table_value(samples, "stack", i)
        frames = get_stack_frames(stack_idx)
        if not frames:
            continue

        raw_samples += 1
        weight = normalize_number(table_value(samples, "weight", i), default=1.0)
        if weight <= 0:
            weight = 1.0
        weighted_samples += weight

        t = normalize_number(table_value(samples, "time", i), default=0.0)
        min_time = t if min_time is None else min(min_time, t)
        max_time = t if max_time is None else max(max_time, t)

        leaf = frames[-1]
        leaf_key = format_function_display(leaf)
        leaf_counter[leaf_key] += weight
        function_details.setdefault(
            leaf_key,
            {
                "name": leaf.get("name"),
                "resource": leaf.get("resource"),
                "file": leaf.get("file"),
                "line": leaf.get("line"),
                "column": leaf.get("column"),
                "is_js": leaf.get("is_js", False),
            },
        )

        if not likely_unsymbolicated(leaf.get("name")):
            named_leaf_samples += weight

        seen_in_sample = set()
        for frame in frames:
            key = format_function_display(frame)
            if key not in seen_in_sample:
                inclusive_counter[key] += weight
                seen_in_sample.add(key)
                function_details.setdefault(
                    key,
                    {
                        "name": frame.get("name"),
                        "resource": frame.get("resource"),
                        "file": frame.get("file"),
                        "line": frame.get("line"),
                        "column": frame.get("column"),
                        "is_js": frame.get("is_js", False),
                    },
                )

        stack_key = stack_display(frames)
        if stack_key:
            stack_counter[stack_key] += weight
            stack_details.setdefault(stack_key, frames)

    marker_length = table_len(markers)
    for i in range(marker_length):
        marker_name = get_string(string_table, table_value(markers, "name", i))
        if marker_name:
            marker_counter[marker_name] += 1

    process_name = (
        thread.get("processName")
        or process_node.get("processName")
        or profile_meta.get("product")
        or None
    )

    notes = []
    if weighted_samples < 100:
        notes.append(
            "Very few weighted samples were collected; treat rankings as low confidence."
        )
    coverage_pct = format_pct(named_leaf_samples, weighted_samples)
    if coverage_pct < 60.0:
        notes.append(
            "Leaf symbol coverage is low; many hotspots may still be raw addresses or placeholders."
        )

    return {
        "thread_key": {
            "process_name": process_name,
            "name": thread.get("name") or "<unnamed-thread>",
            "tid": thread.get("tid"),
            "pid": thread.get("pid"),
        },
        "raw_samples": raw_samples,
        "weighted_samples": round(weighted_samples, 6),
        "named_leaf_samples": round(named_leaf_samples, 6),
        "leaf_symbol_coverage_pct": coverage_pct,
        "duration_ms": round(max_time - min_time, 6) if min_time is not None and max_time is not None else None,
        "leaf_counter": leaf_counter,
        "inclusive_counter": inclusive_counter,
        "stack_counter": stack_counter,
        "function_details": function_details,
        "stack_details": stack_details,
        "marker_counter": marker_counter,
        "notes": notes,
    }


def analyze_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    meta = get_meta(profile)
    threads = []
    total_weighted_samples = 0.0

    for thread, node in iter_threads(profile):
        analyzed = analyze_thread(thread, node, meta)
        threads.append(analyzed)
        total_weighted_samples += analyzed["weighted_samples"]

    threads.sort(
        key=lambda item: (
            -item["weighted_samples"],
            str(item["thread_key"].get("process_name") or ""),
            str(item["thread_key"].get("name") or ""),
            str(item["thread_key"].get("tid") or ""),
        )
    )

    return {
        "meta": {
            "product": meta.get("product"),
            "platform": meta.get("platform"),
            "oscpu": meta.get("oscpu"),
            "interval_ms": meta.get("interval") or meta.get("samplingInterval"),
        },
        "threads": threads,
        "total_weighted_samples": round(total_weighted_samples, 6),
    }


def counter_items_to_public(
    counter: Counter,
    function_details: Dict[str, Dict[str, Any]],
    denominator: float,
    limit: int,
) -> List[Dict[str, Any]]:
    rows = []
    for key, samples in trim_counter(counter, limit):
        details = function_details.get(str(key), {})
        rows.append(
            {
                "function": key,
                "samples": round(samples, 6),
                "pct_of_thread": format_pct(samples, denominator),
                "name": details.get("name"),
                "resource": details.get("resource"),
                "file": details.get("file"),
                "line": details.get("line"),
                "column": details.get("column"),
                "is_js": details.get("is_js"),
            }
        )
    return rows


def stack_items_to_public(
    counter: Counter,
    stack_details: Dict[Tuple[str, ...], List[Dict[str, Any]]],
    denominator: float,
    limit: int,
    max_frames: int = 16,
) -> List[Dict[str, Any]]:
    rows = []
    for key, samples in trim_counter(counter, limit):
        frames = list(key)[-max_frames:]
        rows.append(
            {
                "frames": frames,
                "samples": round(samples, 6),
                "pct_of_thread": format_pct(samples, denominator),
            }
        )
    return rows


def markers_to_public(counter: Counter, limit: int) -> List[Dict[str, Any]]:
    rows = []
    for name, count in trim_counter(counter, limit):
        rows.append({"marker": name, "count": int(count)})
    return rows


def _thread_id_label(thread_key: Dict[str, Any]) -> str:
    process_name = str(thread_key.get("process_name") or "").strip()
    name = str(thread_key.get("name") or "").strip()
    tid = thread_key.get("tid")
    label_parts = []
    if process_name:
        label_parts.append(process_name)
    if name:
        label_parts.append(name)
    label = "/".join(label_parts) if label_parts else "<unnamed>"
    if tid not in (None, ""):
        label = f"{label}#{tid}"
    return label


def _thread_matches(thread_key: Dict[str, Any], queries: List[str]) -> bool:
    if not queries:
        return True
    haystacks = [
        str(thread_key.get("process_name") or "").lower(),
        str(thread_key.get("name") or "").lower(),
        str(thread_key.get("tid") or "").lower(),
    ]
    for query in queries:
        q = query.strip().lower()
        if not q:
            continue
        if any(q in h for h in haystacks):
            return True
    return False


def build_public_report(
    analysis: Dict[str, Any],
    source_path: str,
    *,
    top_threads: int = 12,
    top_functions: int = 15,
    top_stacks: int = 10,
    top_markers: int = 10,
    thread_filters: Optional[List[str]] = None,
) -> Dict[str, Any]:
    filters = [q for q in (thread_filters or []) if q.strip()]
    if filters:
        threads = [
            t for t in analysis["threads"]
            if _thread_matches(t["thread_key"], filters)
        ]
    else:
        threads = analysis["threads"][: max(top_threads, 0)]
    omitted_threads = max(0, len(analysis["threads"]) - len(threads))
    total_weighted = normalize_number(analysis["total_weighted_samples"], default=0.0)

    public_threads = []
    for thread in threads:
        denom = normalize_number(thread["weighted_samples"], default=0.0)
        public_threads.append(
            {
                "thread": {
                    "process_name": thread["thread_key"].get("process_name"),
                    "name": thread["thread_key"].get("name"),
                    "tid": thread["thread_key"].get("tid"),
                    "pid": thread["thread_key"].get("pid"),
                },
                "thread_id_label": _thread_id_label(thread["thread_key"]),
                "weighted_samples": round(denom, 6),
                "raw_samples": int(thread["raw_samples"]),
                "pct_of_profile": format_pct(denom, total_weighted),
                "duration_ms": thread["duration_ms"],
                "leaf_symbol_coverage_pct": thread["leaf_symbol_coverage_pct"],
                "top_leaf_functions": counter_items_to_public(
                    thread["leaf_counter"],
                    thread["function_details"],
                    denom,
                    top_functions,
                ),
                "top_inclusive_functions": counter_items_to_public(
                    thread["inclusive_counter"],
                    thread["function_details"],
                    denom,
                    top_functions,
                ),
                "top_stacks": stack_items_to_public(
                    thread["stack_counter"],
                    thread["stack_details"],
                    denom,
                    top_stacks,
                ),
                "top_markers": markers_to_public(thread["marker_counter"], top_markers),
                "notes": list(thread["notes"]),
            }
        )

    profile_notes = []
    if total_weighted < 100:
        profile_notes.append(
            "The profile contains very few weighted samples overall; expect unstable rankings."
        )
    if public_threads and all(t["leaf_symbol_coverage_pct"] < 60.0 for t in public_threads):
        profile_notes.append(
            "Most top threads have poor leaf symbol coverage; fix symbols before making strong claims."
        )

    return {
        "profile": {
            "source": source_path,
            "product": analysis["meta"].get("product"),
            "platform": analysis["meta"].get("platform"),
            "oscpu": analysis["meta"].get("oscpu"),
            "interval_ms": analysis["meta"].get("interval_ms"),
        },
        "totals": {
            "threads_analyzed": len(analysis["threads"]),
            "threads_returned": len(public_threads),
            "threads_omitted": omitted_threads,
            "weighted_samples": round(total_weighted, 6),
        },
        "threads": public_threads,
        "notes": profile_notes,
    }


def render_markdown(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    profile = report.get("profile", {})
    totals = report.get("totals", {})

    lines.append("# Samply Hotspot Summary")
    lines.append("")
    lines.append(f"- Source: `{profile.get('source')}`")
    if profile.get("product"):
        lines.append(f"- Product: `{profile.get('product')}`")
    if profile.get("platform") or profile.get("oscpu"):
        lines.append(f"- Platform: `{profile.get('platform') or profile.get('oscpu')}`")
    if profile.get("interval_ms") is not None:
        lines.append(f"- Sampling interval: `{profile.get('interval_ms')}` ms")
    lines.append(f"- Weighted samples: `{totals.get('weighted_samples')}`")
    lines.append("")

    for note in report.get("notes", []):
        lines.append(f"> {note}")
    if report.get("notes"):
        lines.append("")

    for thread in report.get("threads", []):
        info = thread["thread"]
        thread_title = thread.get("thread_id_label") or info.get("name") or "<unnamed-thread>"

        lines.append(f"## {thread_title}")
        lines.append("")
        lines.append(
            f"- Weighted samples: `{thread.get('weighted_samples')}` "
            f"({thread.get('pct_of_profile')}% of profile)"
        )
        lines.append(f"- Raw samples: `{thread.get('raw_samples')}`")
        lines.append(f"- Leaf symbol coverage: `{thread.get('leaf_symbol_coverage_pct')}%`")
        if thread.get("duration_ms") is not None:
            lines.append(f"- Observed sample time span: `{thread.get('duration_ms')}` ms")
        lines.append("")

        if thread.get("notes"):
            for note in thread["notes"]:
                lines.append(f"> {note}")
            lines.append("")

        lines.append("### Top leaf functions")
        lines.append("")
        for row in thread.get("top_leaf_functions", []):
            lines.append(
                f"- `{row['function']}` — {row['samples']} samples "
                f"({row['pct_of_thread']}% of thread)"
            )
        if not thread.get("top_leaf_functions"):
            lines.append("- None")
        lines.append("")

        lines.append("### Top inclusive functions")
        lines.append("")
        for row in thread.get("top_inclusive_functions", []):
            lines.append(
                f"- `{row['function']}` — {row['samples']} samples "
                f"({row['pct_of_thread']}% of thread)"
            )
        if not thread.get("top_inclusive_functions"):
            lines.append("- None")
        lines.append("")

        lines.append("### Top stacks")
        lines.append("")
        for row in thread.get("top_stacks", []):
            stack_text = " → ".join(row["frames"])
            lines.append(
                f"- `{stack_text}` — {row['samples']} samples "
                f"({row['pct_of_thread']}% of thread)"
            )
        if not thread.get("top_stacks"):
            lines.append("- None")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def aggregate_threads_for_diff(analysis: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Aggregate threads by logical identity rather than PID/TID.
    Prefer process_name + thread name; fall back to thread name.
    """
    grouped: Dict[str, Dict[str, Any]] = {}

    for thread in analysis["threads"]:
        process_name = thread["thread_key"].get("process_name") or ""
        name = thread["thread_key"].get("name") or "<unnamed-thread>"
        key = f"{process_name}::{name}" if process_name else name

        if key not in grouped:
            grouped[key] = {
                "thread": {
                    "process_name": process_name or None,
                    "name": name,
                },
                "weighted_samples": 0.0,
                "raw_samples": 0,
                "named_leaf_samples": 0.0,
                "leaf_counter": Counter(),
                "inclusive_counter": Counter(),
                "stack_counter": Counter(),
            }

        grouped[key]["weighted_samples"] += normalize_number(thread["weighted_samples"])
        grouped[key]["raw_samples"] += int(thread["raw_samples"])
        grouped[key]["named_leaf_samples"] += normalize_number(thread["named_leaf_samples"])
        grouped[key]["leaf_counter"].update(thread["leaf_counter"])
        grouped[key]["inclusive_counter"].update(thread["inclusive_counter"])
        grouped[key]["stack_counter"].update(thread["stack_counter"])

    for payload in grouped.values():
        payload["weighted_samples"] = round(payload["weighted_samples"], 6)
        payload["leaf_symbol_coverage_pct"] = format_pct(
            payload["named_leaf_samples"], payload["weighted_samples"]
        )

    return grouped


def diff_counter(
    baseline: Counter,
    candidate: Counter,
    baseline_total: float,
    candidate_total: float,
    *,
    top: int,
    stack_mode: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    all_keys = set(baseline) | set(candidate)
    rows = []
    for key in all_keys:
        base_samples = normalize_number(baseline.get(key, 0.0))
        cand_samples = normalize_number(candidate.get(key, 0.0))
        base_pct = format_pct(base_samples, baseline_total)
        cand_pct = format_pct(cand_samples, candidate_total)
        delta_pct = round(cand_pct - base_pct, 4)
        row = {
            "baseline_samples": round(base_samples, 6),
            "candidate_samples": round(cand_samples, 6),
            "baseline_pct": base_pct,
            "candidate_pct": cand_pct,
            "delta_pct": delta_pct,
        }
        if stack_mode:
            row["frames"] = list(key)
        else:
            row["function"] = key
        rows.append(row)

    regressions = sorted(rows, key=lambda r: (-r["delta_pct"], str(r.get("function") or r.get("frames"))))
    improvements = sorted(rows, key=lambda r: (r["delta_pct"], str(r.get("function") or r.get("frames"))))

    regressions = [row for row in regressions if row["delta_pct"] > 0][: max(top, 0)]
    improvements = [row for row in improvements if row["delta_pct"] < 0][: max(top, 0)]
    return regressions, improvements


def build_diff_report(
    baseline_analysis: Dict[str, Any],
    candidate_analysis: Dict[str, Any],
    baseline_source: str,
    candidate_source: str,
    *,
    top: int = 15,
) -> Dict[str, Any]:
    base_grouped = aggregate_threads_for_diff(baseline_analysis)
    cand_grouped = aggregate_threads_for_diff(candidate_analysis)

    all_thread_keys = sorted(set(base_grouped) | set(cand_grouped))

    baseline_total = normalize_number(baseline_analysis["total_weighted_samples"])
    candidate_total = normalize_number(candidate_analysis["total_weighted_samples"])

    global_base_leaf = Counter()
    global_cand_leaf = Counter()
    global_base_inclusive = Counter()
    global_cand_inclusive = Counter()
    global_base_stack = Counter()
    global_cand_stack = Counter()

    for payload in base_grouped.values():
        global_base_leaf.update(payload["leaf_counter"])
        global_base_inclusive.update(payload["inclusive_counter"])
        global_base_stack.update(payload["stack_counter"])

    for payload in cand_grouped.values():
        global_cand_leaf.update(payload["leaf_counter"])
        global_cand_inclusive.update(payload["inclusive_counter"])
        global_cand_stack.update(payload["stack_counter"])

    global_leaf_regressions, global_leaf_improvements = diff_counter(
        global_base_leaf, global_cand_leaf, baseline_total, candidate_total, top=top
    )
    global_inclusive_regressions, global_inclusive_improvements = diff_counter(
        global_base_inclusive,
        global_cand_inclusive,
        baseline_total,
        candidate_total,
        top=top,
    )
    global_stack_regressions, global_stack_improvements = diff_counter(
        global_base_stack,
        global_cand_stack,
        baseline_total,
        candidate_total,
        top=top,
        stack_mode=True,
    )

    thread_rows = []
    for key in all_thread_keys:
        base = base_grouped.get(
            key,
            {
                "thread": {"process_name": None, "name": key},
                "weighted_samples": 0.0,
                "raw_samples": 0,
                "leaf_symbol_coverage_pct": 0.0,
                "leaf_counter": Counter(),
                "inclusive_counter": Counter(),
                "stack_counter": Counter(),
            },
        )
        cand = cand_grouped.get(
            key,
            {
                "thread": {"process_name": None, "name": key},
                "weighted_samples": 0.0,
                "raw_samples": 0,
                "leaf_symbol_coverage_pct": 0.0,
                "leaf_counter": Counter(),
                "inclusive_counter": Counter(),
                "stack_counter": Counter(),
            },
        )

        leaf_regressions, leaf_improvements = diff_counter(
            base["leaf_counter"],
            cand["leaf_counter"],
            normalize_number(base["weighted_samples"]),
            normalize_number(cand["weighted_samples"]),
            top=top,
        )
        inclusive_regressions, inclusive_improvements = diff_counter(
            base["inclusive_counter"],
            cand["inclusive_counter"],
            normalize_number(base["weighted_samples"]),
            normalize_number(cand["weighted_samples"]),
            top=top,
        )
        stack_regressions, stack_improvements = diff_counter(
            base["stack_counter"],
            cand["stack_counter"],
            normalize_number(base["weighted_samples"]),
            normalize_number(cand["weighted_samples"]),
            top=top,
            stack_mode=True,
        )

        notes = []
        if normalize_number(base["weighted_samples"]) < 100 or normalize_number(cand["weighted_samples"]) < 100:
            notes.append("At least one side has few weighted samples; per-thread deltas may be noisy.")
        if base["leaf_symbol_coverage_pct"] < 60.0 or cand["leaf_symbol_coverage_pct"] < 60.0:
            notes.append("Symbol coverage is weak on at least one side; address-heavy deltas may be misleading.")

        thread_rows.append(
            {
                "thread": base["thread"] if base["thread"].get("name") else cand["thread"],
                "baseline_weighted_samples": round(normalize_number(base["weighted_samples"]), 6),
                "candidate_weighted_samples": round(normalize_number(cand["weighted_samples"]), 6),
                "baseline_leaf_symbol_coverage_pct": round(normalize_number(base["leaf_symbol_coverage_pct"]), 4),
                "candidate_leaf_symbol_coverage_pct": round(normalize_number(cand["leaf_symbol_coverage_pct"]), 4),
                "leaf_regressions": leaf_regressions,
                "leaf_improvements": leaf_improvements,
                "inclusive_regressions": inclusive_regressions,
                "inclusive_improvements": inclusive_improvements,
                "stack_regressions": stack_regressions,
                "stack_improvements": stack_improvements,
                "notes": notes,
            }
        )

    return {
        "baseline": {
            "source": baseline_source,
            "product": baseline_analysis["meta"].get("product"),
            "platform": baseline_analysis["meta"].get("platform"),
            "weighted_samples": round(baseline_total, 6),
        },
        "candidate": {
            "source": candidate_source,
            "product": candidate_analysis["meta"].get("product"),
            "platform": candidate_analysis["meta"].get("platform"),
            "weighted_samples": round(candidate_total, 6),
        },
        "matching_strategy": "Threads are aggregated by process_name + thread name when available, else by thread name.",
        "global": {
            "leaf_regressions": global_leaf_regressions,
            "leaf_improvements": global_leaf_improvements,
            "inclusive_regressions": global_inclusive_regressions,
            "inclusive_improvements": global_inclusive_improvements,
            "stack_regressions": global_stack_regressions,
            "stack_improvements": global_stack_improvements,
        },
        "threads": thread_rows,
        "notes": [
            "Deltas are normalized by each profile's weighted sample totals, not by raw sample counts.",
            "Treat apparent regressions skeptically when symbol coverage is poor or weighted sample counts are low.",
        ],
    }


def render_diff_markdown(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Samply Profile Diff")
    lines.append("")
    lines.append(f"- Baseline: `{report['baseline']['source']}` ({report['baseline']['weighted_samples']} weighted samples)")
    lines.append(f"- Candidate: `{report['candidate']['source']}` ({report['candidate']['weighted_samples']} weighted samples)")
    lines.append("")
    for note in report.get("notes", []):
        lines.append(f"> {note}")
    lines.append("")

    lines.append("## Global leaf regressions")
    lines.append("")
    for row in report["global"].get("leaf_regressions", []):
        lines.append(
            f"- `{row['function']}`: {row['baseline_pct']}% → {row['candidate_pct']}% "
            f"({row['delta_pct']} pts)"
        )
    if not report["global"].get("leaf_regressions"):
        lines.append("- None")
    lines.append("")

    lines.append("## Global leaf improvements")
    lines.append("")
    for row in report["global"].get("leaf_improvements", []):
        lines.append(
            f"- `{row['function']}`: {row['baseline_pct']}% → {row['candidate_pct']}% "
            f"({row['delta_pct']} pts)"
        )
    if not report["global"].get("leaf_improvements"):
        lines.append("- None")
    lines.append("")

    for thread in report.get("threads", []):
        info = thread["thread"]
        title = info.get("name") or "<unnamed-thread>"
        if info.get("process_name"):
            title = f"{info['process_name']} / {title}"
        lines.append(f"## {title}")
        lines.append("")
        lines.append(
            f"- Baseline weighted samples: `{thread['baseline_weighted_samples']}` "
            f"(coverage {thread['baseline_leaf_symbol_coverage_pct']}%)"
        )
        lines.append(
            f"- Candidate weighted samples: `{thread['candidate_weighted_samples']}` "
            f"(coverage {thread['candidate_leaf_symbol_coverage_pct']}%)"
        )
        lines.append("")
        for note in thread.get("notes", []):
            lines.append(f"> {note}")
        if thread.get("notes"):
            lines.append("")
        lines.append("### Leaf regressions")
        lines.append("")
        for row in thread.get("leaf_regressions", []):
            lines.append(
                f"- `{row['function']}`: {row['baseline_pct']}% → {row['candidate_pct']}% "
                f"({row['delta_pct']} pts)"
            )
        if not thread.get("leaf_regressions"):
            lines.append("- None")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
