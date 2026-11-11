"""Behavior tests for sketchup_link/server.rb on the main-thread timer.

The Ruby side runs in a subprocess (see ruby_test_helpers/server_test.rb),
with a UI.start_timer stub that behaves like SketchUp's one-shot default.
"""
from __future__ import annotations

import json

from tests.unit.conftest import run_ruby

SCRIPT = "server_test.rb"
STATUS_REQUEST = "GET /status HTTP/1.1\r\nHost: localhost\r\n\r\n"
SUBSCRIBE_REQUEST = "GET /subscribe?events=* HTTP/1.1\r\nHost: localhost\r\n\r\n"


def _session(tmp_path, *steps):
    socket_path = str(tmp_path / "server.sock")
    commands = [{"op": "start", "socket_path": socket_path}, *steps]
    return run_ruby(SCRIPT, commands)["results"]


def _body(response: str) -> str:
    _, _, body = response.partition("\r\n\r\n")
    return body


class TestRequestServicing:
    def test_request_is_not_answered_until_timer_ticks(self, tmp_path):
        results = _session(
            tmp_path,
            {"op": "connect", "id": "c"},
            {"op": "send", "id": "c", "data": STATUS_REQUEST},
            {"op": "read", "id": "c"},
            {"op": "tick"},
            {"op": "read", "id": "c"},
        )
        assert results[3]["data"] == ""
        assert results[5]["data"].startswith("HTTP/1.1 200")

    def test_timer_keeps_servicing_requests_across_ticks(self, tmp_path):
        results = _session(
            tmp_path,
            {"op": "connect", "id": "first"},
            {"op": "send", "id": "first", "data": STATUS_REQUEST},
            {"op": "tick"},
            {"op": "read", "id": "first"},
            {"op": "connect", "id": "second"},
            {"op": "send", "id": "second", "data": STATUS_REQUEST},
            {"op": "tick"},
            {"op": "read", "id": "second"},
        )
        assert results[4]["data"].startswith("HTTP/1.1 200")
        assert results[8]["data"].startswith("HTTP/1.1 200")

    def test_request_split_across_writes_is_buffered_until_headers_end(self, tmp_path):
        results = _session(
            tmp_path,
            {"op": "connect", "id": "c"},
            {"op": "send", "id": "c", "data": "GET /sta"},
            {"op": "tick"},
            {"op": "read", "id": "c"},
            {"op": "send", "id": "c", "data": "tus HTTP/1.1\r\nHost: localhost\r\n\r\n"},
            {"op": "tick"},
            {"op": "read", "id": "c"},
        )
        assert results[4]["data"] == ""
        assert results[7]["data"].startswith("HTTP/1.1 200")

    def test_status_reports_zero_subscriptions_initially(self, tmp_path):
        results = _session(
            tmp_path,
            {"op": "connect", "id": "c"},
            {"op": "send", "id": "c", "data": STATUS_REQUEST},
            {"op": "tick"},
            {"op": "read", "id": "c"},
        )
        status = json.loads(_body(results[4]["data"]))
        assert status["subscriptions"] == 0


class TestSubscribe:
    def test_subscriber_socket_stays_open_and_receives_dispatched_events(self, tmp_path):
        results = _session(
            tmp_path,
            {"op": "connect", "id": "sub"},
            {"op": "send", "id": "sub", "data": SUBSCRIBE_REQUEST},
            {"op": "tick"},
            {"op": "dispatch", "event": "test_event", "data": {"ok": True}},
            {"op": "read", "id": "sub"},
        )
        streamed = results[5]["data"]
        assert '"ok":true' in streamed


class TestStop:
    def test_stop_cancels_timer_and_refuses_new_connections(self, tmp_path):
        results = _session(
            tmp_path,
            {"op": "stop"},
            {"op": "timers"},
            {"op": "try_connect"},
        )
        assert results[2] == {"count": 0}
        assert results[3] == {"connected": False}
