#!/usr/bin/env python3
"""
diagnose.py — CLI tool for producing readable failure reports from
test artifact directories.

Usage:
    python tests/observability/diagnose.py tests/fuzz/artifacts/<test_name>/

Reads events.jsonl, model_baseline.json, model_after.json, and violations.json
from the artifact directory and prints a human-readable report to stdout.
"""

import argparse
import json
import os
import sys


def diagnose(artifact_dir):
    """Produce a human-readable failure report from an artifact directory.

    Args:
        artifact_dir: path to a test artifact directory.

    Returns:
        str: the formatted report.
    """
    lines = []
    lines.append("=" * 72)
    lines.append(f"FAILURE DIAGNOSTIC REPORT")
    lines.append(f"Artifact directory: {artifact_dir}")
    lines.append("=" * 72)

    # ------------------------------------------------------------------
    # 1. Event timeline
    # ------------------------------------------------------------------
    events_path = os.path.join(artifact_dir, "events.jsonl")
    if not os.path.exists(events_path):
        lines.append("\n[WARN] No events.jsonl found — event log missing.")
        events = []
    else:
        events = _load_events(events_path)
        lines.append(f"\n--- Event Timeline ({len(events)} events) ---")
        for i, evt in enumerate(events):
            ts = evt.get("ts", "?")
            etype = evt.get("type", "?")
            data = evt.get("data", {})
            summary = _summarize_event(etype, data)
            lines.append(f"  [{i}] {ts}  {etype}: {summary}")
            _render_event_detail(lines, etype, data)

    # ------------------------------------------------------------------
    # 2. Mutation summary
    # ------------------------------------------------------------------
    mutation_events = [e for e in events if e.get("type") == "mutation"]
    if mutation_events:
        lines.append(f"\n--- Mutations Applied ({len(mutation_events)}) ---")
        for i, me in enumerate(mutation_events):
            data = me.get("data", {})
            strategy = data.get("strategy", "?")
            params = data.get("params", {})
            result = data.get("result")
            lines.append(f"  [{i}] {strategy}")
            if params:
                lines.append(f"       params: {_truncate(json.dumps(params), 200)}")
            if result:
                lines.append(f"       result: {_truncate(json.dumps(result), 150)}")

    # ------------------------------------------------------------------
    # 3. Invariant violations
    # ------------------------------------------------------------------
    violations_path = os.path.join(artifact_dir, "violations.json")
    if os.path.exists(violations_path):
        try:
            with open(violations_path) as f:
                violations = json.load(f)
            if violations:
                lines.append(f"\n--- Invariant Violations ({len(violations)}) ---")
                for i, v in enumerate(violations):
                    lines.append(f"  [{i}] {v.get('check', '?')}: {v.get('message', '?')}")
                    details = v.get("details", {})
                    if details:
                        lines.append(f"       details: {json.dumps(details, default=str)}")
            else:
                lines.append("\n--- Invariant Violations: NONE ---")
        except (json.JSONDecodeError, OSError) as exc:
            lines.append(f"\n[WARN] Could not read violations.json: {exc}")
    else:
        # Check assertion events for failures
        failed_assertions = [e for e in events
                             if e.get("type") == "assertion"
                             and e.get("data", {}).get("passed") is False]
        if failed_assertions:
            lines.append(f"\n--- Failed Assertions ({len(failed_assertions)}) ---")
            for fa in failed_assertions:
                d = fa.get("data", {})
                lines.append(f"  - {d.get('name', '?')}: {d.get('details', {})}")
        else:
            # Check for error events
            error_events = [e for e in events if e.get("type") == "error"]
            if error_events:
                lines.append(f"\n--- Error Events ({len(error_events)}) ---")
                for ee in error_events:
                    d = ee.get("data", {})
                    lines.append(f"  - {d.get('error_type', '?')}: {d.get('details', {})}")
            else:
                lines.append("\n--- No violations or failures recorded ---")

    # ------------------------------------------------------------------
    # 4. Model diff summary
    # ------------------------------------------------------------------
    model_diff_path = os.path.join(artifact_dir, "model_diff.json")
    if os.path.exists(model_diff_path):
        try:
            with open(model_diff_path) as f:
                diff = json.load(f)
            summary = diff.get("summary", {})
            lines.append(f"\n--- Model Diff Summary ---")
            if summary:
                for key, val in summary.items():
                    if val:
                        lines.append(f"  {key}: {val}")
            else:
                lines.append("  No structural changes detected.")
        except (json.JSONDecodeError, OSError) as exc:
            lines.append(f"\n[WARN] Could not read model_diff.json: {exc}")

    # ------------------------------------------------------------------
    # 5. Screenshot info
    # ------------------------------------------------------------------
    for fname in ("sketchup_before.png", "sketchup_after.png",
                  "screenshot_diff.png", "model_baseline.png", "model_after.png"):
        fpath = os.path.join(artifact_dir, fname)
        if os.path.exists(fpath):
            size = os.path.getsize(fpath)
            lines.append(f"\n  {fname}: {size} bytes")

    # ------------------------------------------------------------------
    # 6. Model files
    # ------------------------------------------------------------------
    for fname in ("model_baseline.json", "model_after.json"):
        fpath = os.path.join(artifact_dir, fname)
        if os.path.exists(fpath):
            try:
                with open(fpath) as f:
                    data = json.load(f)
                ec = len(data.get("entities", []))
                mc = len(data.get("materials", []))
                lc = len(data.get("layers", []))
                lines.append(f"\n  {fname}: {ec} entities, {mc} materials, {lc} layers")
            except (json.JSONDecodeError, OSError) as exc:
                lines.append(f"\n  {fname}: [error reading: {exc}]")

    lines.append("\n" + "=" * 72)
    return "\n".join(lines)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _load_events(path):
    """Load JSON-lines event file into a list of dicts."""
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    events.append({"ts": "?", "type": "parse_error",
                                   "data": {"raw": line[:200]}})
    return events


def _summarize_event(etype, data):
    """Return a one-line summary of an event."""
    if etype == "api_call":
        return f"{data.get('method', '?')} {data.get('path', '?')} → {data.get('status', '?')}"
    elif etype == "model_snapshot":
        label = data.get("label", "?")
        ec = data.get("entity_count", "?")
        return f"label={label} ({ec} entities)"
    elif etype == "assertion":
        passed = data.get("passed")
        return f"{data.get('name', '?')}: {'PASS' if passed else 'FAIL'}"
    elif etype == "screenshot":
        return f"{data.get('label', '?')} ({data.get('size_bytes', '?')}b)"
    elif etype == "mutation":
        return f"{data.get('strategy', '?')}"
    elif etype == "error":
        return f"{data.get('error_type', '?')}"
    elif etype == "session_start":
        return "session started"
    elif etype == "session_end":
        return "session ended"
    elif etype == "session_error":
        return f"EXCEPTION: {data.get('message', '?')}"
    return ""


def _render_event_detail(lines, etype, data):
    """Add detail lines for certain event types."""
    if etype == "session_error":
        lines.append(f"    type: {data.get('type', '?')}")
        lines.append(f"    message: {data.get('message', '?')}")
    elif etype == "error":
        details = data.get("details", {})
        if details:
            lines.append(f"    details: {json.dumps(details, default=str)}")


def _truncate(s, maxlen=200):
    """Truncate a string with ellipsis if too long."""
    if len(s) > maxlen:
        return s[:maxlen] + "..."
    return s


def main():
    parser = argparse.ArgumentParser(
        description="Produce a readable failure report from a fuzz test artifact directory."
    )
    parser.add_argument(
        "artifact_dir",
        help="Path to a test artifact directory (e.g. tests/fuzz/artifacts/<test_name>/)",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.artifact_dir):
        print(f"Error: not a directory: {args.artifact_dir}", file=sys.stderr)
        sys.exit(1)

    report = diagnose(args.artifact_dir)
    print(report)


if __name__ == "__main__":
    main()
