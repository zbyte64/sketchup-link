"""
test_fuzz.py — Parametrized fuzz test runner.

Test flow per mutation strategy:
    1. Fetch baseline model snapshot
    2. Log baseline
    3. Apply mutation
    4. Fetch post-mutation model snapshot
    5. Run invariant checkers
    6. Report violations

Two modes: --fuzz-mock (CI-safe, default) and --fuzz-real (against VM).

Usage:
    uv run pytest tests/fuzz/ -v --fuzz-mock
    uv run pytest tests/fuzz/ -v --fuzz-real
"""

import json
import os
import time

import pytest

from tests.fuzz.mutations import all_strategies
from tests.fuzz.invariants import check_all


pytestmark = pytest.mark.fuzz


def _save_json(artifact_dir, name, data):
    """Save a JSON dict to the artifact directory."""
    path = os.path.join(artifact_dir, name)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def _fetch_model(transport):
    """Fetch model JSON via the configured transport."""
    if transport["mode"] == "tcp":
        import http.client
        conn = http.client.HTTPConnection(transport["host"], transport["port"], timeout=10)
        try:
            conn.request("GET", "/model")
            resp = conn.getresponse()
            assert resp.status == 200, f"GET /model returned HTTP {resp.status}"
            return json.loads(resp.read())
        finally:
            conn.close()
    else:
        import socket
        from http.client import HTTPConnection as _Base

        class _UnixConn(_Base):
            def __init__(self, path):
                super().__init__("localhost")
                self._path = path

            def connect(self):
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(self._path)
                self.sock = s

        conn = _UnixConn(transport["socket_path"])
        try:
            conn.request("GET", "/model")
            resp = conn.getresponse()
            assert resp.status == 200, f"GET /model returned HTTP {resp.status}"
            return json.loads(resp.read())
        finally:
            conn.close()


def _build_strategies(transport):
    """Build strategy instances for the given transport."""
    socket_path = transport.get("socket_path")
    host = transport.get("host", "127.0.0.1")
    port = transport.get("port", 9876)
    return all_strategies(host=host, port=port, socket_path=socket_path)


# ------------------------------------------------------------------
# Parametrized test: one per mutation strategy
# ------------------------------------------------------------------


@pytest.mark.parametrize("strategy", [
    pytest.param(s, id=s.name)
    for s in _build_strategies({"mode": "unix", "socket_path": None})
], scope="module")
def test_mutation_strategy(strategy, fuzz_transport, artifact_dir, event_logger):
    """Apply a single mutation strategy and verify invariants hold.

    The strategy instance is already parametrized with default transport;
    we update its transport config for the actual run.
    """
    # Update transport on the existing instance
    strategy.host = fuzz_transport.get("host", "127.0.0.1")
    strategy.port = fuzz_transport.get("port", 9876)
    strategy.socket_path = fuzz_transport.get("socket_path")

    # 1. Fetch baseline
    event_logger.api_call("GET", "/model")
    baseline = _fetch_model(fuzz_transport)
    event_logger.model_snapshot("baseline", baseline)
    _save_json(artifact_dir, "model_baseline.json", baseline)

    # 2. Check baseline invariants
    baseline_violations = check_all(baseline, event_logger)
    if baseline_violations:
        _save_json(artifact_dir, "violations_baseline.json", baseline_violations)
        event_logger.error("baseline_invariant_violation",
                           {"count": len(baseline_violations)})

    # 3. Apply mutation
    result = strategy.apply()
    event_logger.mutation(strategy.name, result.get("params", {}), result)
    event_logger.api_call("POST", f"/control/{strategy.name}",
                          result.get("params"), result.get("status"), result.get("response"))

    # If mutation was skipped, we still check post-mutation state
    if result.get("skipped"):
        event_logger.assertion("mutation_applied", passed=False,
                               details={"reason": "mutation skipped"})

    # Brief pause for model state to stabilize
    time.sleep(0.05)

    # 4. Fetch post-mutation model
    event_logger.api_call("GET", "/model")
    after = _fetch_model(fuzz_transport)
    event_logger.model_snapshot("after_mutation", after)
    after_path = _save_json(artifact_dir, "model_after.json", after)

    # 5. Compute model diff
    from tests.observability.model_diff import ModelDiffer
    differ = ModelDiffer()
    diff = differ.compare(baseline, after)
    diff_path = _save_json(artifact_dir, "model_diff.json", diff)

    # 6. Run invariant checkers on post-mutation model
    violations = check_all(after, event_logger)
    violations_path = _save_json(artifact_dir, "violations.json", violations)

    # 7. Assert no violations
    if violations:
        failure_messages = "\n".join(
            f"  [{v['check']}] {v['message']}" for v in violations
        )
        event_logger.error("test_failure", {"violations": len(violations)})
        pytest.fail(
            f"Invariant violations after mutation '{strategy.name}' "
            f"({len(violations)} total):\n{failure_messages}"
        )
