"""Contract tests for RemoteControl.handle: every route answers [status, body].

Regression guard for the defect where success handlers returned a bare hash and
the caller wrote it into the HTTP status line.
"""

from __future__ import annotations

import pytest

from tests.unit.conftest import run_ruby


@pytest.mark.ruby
class TestHandleSuccessShape:
    def test_bare_hash_success_is_wrapped_as_200(self):
        r = run_ruby("remote_control_handle_test.rb", {"route": "camera", "stub_kind": "hash"})
        assert r == {"status": 200, "body": {"ok": True}}

    def test_error_pair_passes_through_unchanged(self):
        r = run_ruby("remote_control_handle_test.rb", {"route": "camera", "stub_kind": "pair"})
        assert r == {"status": 400, "body": {"error": "stubbed"}}

    def test_unknown_route_is_404(self):
        r = run_ruby("remote_control_handle_test.rb", {"route": "no/such/route", "stub_kind": ""})
        assert r["status"] == 404
