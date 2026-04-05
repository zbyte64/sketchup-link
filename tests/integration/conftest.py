"""
tests/integration/conftest.py

Session-scoped fixtures that:
  1. Add the sketchup_link package to sys.path so live_adapter can be imported
     without installing anything.
  2. Spawn the Ruby mock server as a subprocess and block until it signals
     "ready" on stdout.
  3. Fetch the model JSON once per session and expose it as JsonModel.

Socket path uses -test.sock suffix to avoid colliding with a live SketchUp
instance running on the same machine.
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
# Make sketchup_link importable — add shared/project/ext/sketchup-link to path
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
_ADAPTER_DIR = os.path.join(
    _REPO_ROOT, 
)

if _ADAPTER_DIR not in sys.path:
    sys.path.insert(0, _ADAPTER_DIR)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SERVER_RB = os.path.join(os.path.dirname(__file__), 'server.rb')
_SOCKET_PATH = os.path.join(tempfile.gettempdir(), 'sketchup-link-test.sock')


# ---------------------------------------------------------------------------
# Unix-socket HTTP helper (mirrors live_adapter._UnixSocketHTTPConnection)
# ---------------------------------------------------------------------------

class _UnixSocketHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__('localhost')
        self._path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(self._path)
        self.sock = s


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def ruby_server():
    """
    Start the Ruby test server subprocess.

    Blocks until the server writes "ready" to stdout, then yields the socket
    path. Sends SIGTERM on teardown and waits up to 5 s; falls back to SIGKILL.
    """
    if os.path.exists(_SOCKET_PATH):
        os.unlink(_SOCKET_PATH)

    proc = subprocess.Popen(
        ['ruby', _SERVER_RB, _SOCKET_PATH],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    signal = proc.stdout.readline().strip()
    if signal != 'ready':
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


@pytest.fixture(scope='session')
def model_data(ruby_server):
    """
    Fetch the model JSON from the Ruby server once per session.
    Returns the raw parsed dict.
    """
    conn = _UnixSocketHTTPConnection(ruby_server)
    try:
        conn.request('GET', '/model')
        resp = conn.getresponse()
        assert resp.status == 200, f"Expected HTTP 200, got {resp.status}"
        return json.loads(resp.read())
    finally:
        conn.close()


@pytest.fixture(scope='session')
def json_model(model_data):
    """Wrap model_data in JsonModel. Session-scoped — all tests share one instance."""
    from sketchup_link.live_adapter import JsonModel
    return JsonModel(model_data)
