"""
EventLogger — Structured JSON-lines event logger for E2E test observability.

Writes timestamped events as newline-delimited JSON to a per-test artifact
directory. Designed as a context manager for automatic setup/teardown.

Usage:
    with EventLogger(artifact_dir) as log:
        log.api_call("POST", "/control/geometry/face", body)
        log.model_snapshot("after_mutation", model_json)
        log.assertion("non_degenerate_faces", passed=True)
        log.screenshot("sketchup_before", "/tmp/screenshot.png")
        log.mutation("AddFaceMutation", {"points": [...]})
        log.error("invariant_violation", {"description": "..."})
"""

import json
import os
import threading
from datetime import datetime, timezone


class EventLogger:
    """Context manager that writes structured JSON-lines to events.jsonl.

    Each event dict has at least:
        ts   — ISO-8601 UTC timestamp
        type — event type string
        data — event-specific payload (dict)

    Thread-safe: uses a per-write lock.
    """

    def __init__(self, artifact_dir):
        self._artifact_dir = artifact_dir
        self._path = os.path.join(artifact_dir, "events.jsonl")
        self._lock = threading.Lock()
        self._fh = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        os.makedirs(self._artifact_dir, exist_ok=True)
        self._fh = open(self._path, "w", encoding="utf-8")
        self._write("session_start", {"artifact_dir": self._artifact_dir})
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._write("session_error", {
                "type": exc_type.__name__,
                "message": str(exc_val),
            })
        self._write("session_end", {})
        if self._fh:
            self._fh.close()
            self._fh = None

    # ------------------------------------------------------------------
    # Public event helpers
    # ------------------------------------------------------------------

    def api_call(self, method, path, request_body=None, status=None, response=None):
        """Log an API call event."""
        self._write("api_call", {
            "method": method,
            "path": path,
            "request_body": _safe_json(request_body),
            "status": status,
            "response": _safe_json(response),
        })

    def model_snapshot(self, label, model_json):
        """Log a model snapshot event.

        label identifies the point in the test flow (e.g. "baseline",
        "after_mutation"). model_json is the full JSON dict.
        """
        self._write("model_snapshot", {
            "label": label,
            "entity_count": len(model_json.get("entities", [])),
            "material_count": len(model_json.get("materials", [])),
            "layer_count": len(model_json.get("layers", [])),
        })

    def assertion(self, name, passed, details=None):
        """Log an assertion/check result."""
        self._write("assertion", {
            "name": name,
            "passed": passed,
            "details": details or {},
        })

    def screenshot(self, label, file_path):
        """Log a screenshot capture."""
        size = os.path.getsize(file_path) if file_path and os.path.exists(file_path) else None
        self._write("screenshot", {
            "label": label,
            "file_path": file_path,
            "size_bytes": size,
        })

    def mutation(self, strategy_name, params, result=None):
        """Log a mutation application."""
        self._write("mutation", {
            "strategy": strategy_name,
            "params": _safe_json(params),
            "result": _safe_json(result),
        })

    def error(self, error_type, details=None):
        """Log an error or invariant violation."""
        self._write("error", {
            "error_type": error_type,
            "details": details or {},
        })

    # ------------------------------------------------------------------
    # Core write
    # ------------------------------------------------------------------

    def _write(self, event_type, data):
        """Write a single JSON line to the log file."""
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "data": data,
        }
        line = json.dumps(event, default=str) + "\n"
        with self._lock:
            if self._fh:
                self._fh.write(line)
                self._fh.flush()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def artifact_dir(self):
        return self._artifact_dir

    @property
    def log_path(self):
        return self._path


def _safe_json(obj):
    """Serialize obj to a JSON-safe representation, or None if not possible."""
    if obj is None:
        return None
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return repr(obj)
