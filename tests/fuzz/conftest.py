"""
tests/fuzz/conftest.py — Fuzz-specific fixtures.

Supports two modes:
    --fuzz-real: POST against the real SketchUp VM (TCP mode)
    --fuzz-mock: POST against the Ruby mock server (Unix socket, CI-safe)

Default is --fuzz-mock (CI-safe).
"""

import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile

import pytest


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SERVER_RB = os.path.join(_REPO_ROOT, "tests", "integration", "server.rb")
_SOCKET_PATH = os.path.join(tempfile.gettempdir(), "sketchup-link-fuzz-test.sock")
_ARTIFACT_BASE = os.path.join(_REPO_ROOT, "tests", "fuzz", "artifacts")

# TCP defaults for --fuzz-real mode
_TCP_HOST = "127.0.0.1"
_TCP_PORT = 9876


# ---------------------------------------------------------------------------
# CLI options
# ---------------------------------------------------------------------------


def pytest_addoption(parser):
    parser.addoption(
        "--fuzz-real",
        action="store_true",
        default=False,
        help="Run fuzz tests against real SketchUp VM (TCP mode)",
    )
    parser.addoption(
        "--fuzz-mock",
        action="store_true",
        default=False,
        help="Run fuzz tests against Ruby mock server (CI-safe, default)",
    )


def pytest_configure(config):
    # Register marker
    config.addinivalue_line("markers", "fuzz: fuzz tests for mutation-based testing")

    # If neither flag is set or both are set, default to mock
    fuzz_real = config.getoption("--fuzz-real")
    fuzz_mock = config.getoption("--fuzz-mock")
    if fuzz_real and not fuzz_mock:
        config._fuzz_mode = "real"
    else:
        config._fuzz_mode = "mock"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def fuzz_mode(request):
    """Return 'mock' or 'real' depending on --fuzz-* flags."""
    return request.config._fuzz_mode


@pytest.fixture(scope="session")
def ruby_server():
    """Start the Ruby mock server for fuzz testing (mock mode only)."""
    if os.path.exists(_SOCKET_PATH):
        os.unlink(_SOCKET_PATH)

    proc = subprocess.Popen(
        ["ruby", _SERVER_RB, _SOCKET_PATH],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    signal = proc.stdout.readline().strip()
    if signal != "ready":
        proc.terminate()
        stderr_out = proc.stderr.read()
        raise RuntimeError(
            f"Ruby server did not signal 'ready' (got {signal!r}).\n"
            f"stderr:\n{stderr_out}"
        )

    yield _SOCKET_PATH

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    try:
        os.unlink(_SOCKET_PATH)
    except FileNotFoundError:
        pass


@pytest.fixture(scope="session")
def fuzz_transport(fuzz_mode, ruby_server):
    """Return a dict with transport configuration.

    In mock mode: {'mode': 'unix', 'socket_path': ...}
    In real mode: {'mode': 'tcp', 'host': ..., 'port': ...}
    """
    if fuzz_mode == "real":
        return {"mode": "tcp", "host": _TCP_HOST, "port": _TCP_PORT, "socket_path": None}
    return {"mode": "unix", "socket_path": ruby_server, "host": None, "port": None}


@pytest.fixture
def artifact_dir(request):
    """Per-test artifact directory for observability output."""
    test_name = request.node.name.replace("/", "_").replace(" ", "_").replace("[", "_").replace("]", "_")
    path = os.path.join(_ARTIFACT_BASE, test_name)
    os.makedirs(path, exist_ok=True)
    return path


@pytest.fixture
def event_logger(artifact_dir):
    """Create an EventLogger instance for the current test."""
    from tests.observability.event_logger import EventLogger
    with EventLogger(artifact_dir) as log:
        yield log
