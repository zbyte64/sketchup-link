"""Tests for SubscriptionManager via Ruby subprocess."""

from __future__ import annotations

import re

import pytest

from tests.unit.conftest import run_ruby

SCRIPT = "subscription_manager_test.rb"


@pytest.mark.ruby
class TestSubscriptionManagerRuby:
    """Tests for SubscriptionManager using the Ruby helper script."""

    def test_subscribe_returns_uuid(self) -> None:
        """Subscribe returns a UUID-like string."""
        results = run_ruby(SCRIPT, [{"action": "subscribe", "events": ["*"]}])
        assert len(results) == 1
        rid = results[0]["id"]
        assert isinstance(rid, str)
        assert re.match(r"^[0-9a-f\-]{36}$", rid)

    def test_unsubscribe_removes_entry(self) -> None:
        """After unsubscribe the subscription is removed."""
        results = run_ruby(SCRIPT, [
            {"action": "subscribe", "events": ["*"]},
            {"action": "status"},
        ])
        assert results[1]["subscriptions"] == 1
        sub_id = results[0]["id"]

        # A fresh manager; unsubscribe with a valid UUID exercises the path.
        results2 = run_ruby(SCRIPT, [
            {"action": "unsubscribe", "id": sub_id},
            {"action": "status"},
        ])
        assert results2[0]["ok"] is True
        assert results2[1]["subscriptions"] == 0

    def test_unsubscribe_nonexistent_noop(self) -> None:
        """Unsubscribe of a nonexistent id does not raise."""
        results = run_ruby(SCRIPT, [
            {"action": "unsubscribe_nonexistent",
             "id": "00000000-0000-0000-0000-000000000000"},
            {"action": "status"},
        ])
        assert results[0]["ok"] is True
        assert results[1]["subscriptions"] == 0

    def test_dispatch_star_matches_all(self) -> None:
        """Subscriber with ['*'] receives all dispatched events."""
        results = run_ruby(SCRIPT, [
            {"action": "subscribe", "events": ["*"]},
            {"action": "dispatch", "event": "entity_added", "payload": {"v": 1}},
            {"action": "dispatch", "event": "entity_modified", "payload": {"v": 2}},
        ])
        # First dispatch produced one write; second dispatch accumulated both.
        assert len(results[1]["writes"]) == 1
        assert len(results[2]["writes"]) == 2

    def test_dispatch_specific_event(self) -> None:
        """Subscriber with a specific event only receives that event."""
        results = run_ruby(SCRIPT, [
            {"action": "subscribe", "events": ["entity_added"]},
            {"action": "dispatch", "event": "entity_added", "payload": {"v": 1}},
            {"action": "dispatch", "event": "entity_modified", "payload": {"v": 2}},
        ])
        # entity_added matched (1 write), entity_modified did not (still 1).
        assert len(results[1]["writes"]) == 1
        assert len(results[2]["writes"]) == 1

    def test_dispatch_non_matching_skipped(self) -> None:
        """Subscriber does not receive non-matching events."""
        results = run_ruby(SCRIPT, [
            {"action": "subscribe", "events": ["entity_added"]},
            {"action": "dispatch", "event": "entity_modified", "payload": {"v": 1}},
        ])
        assert len(results[1]["writes"]) == 0

    def test_dispatch_dead_socket_pruned(self) -> None:
        """Dispatch to a dead socket prunes the subscription."""
        results = run_ruby(SCRIPT, [
            {"action": "dispatch_dead", "event": "entity_added",
             "payload": {"v": 1}},
        ])
        assert results[0]["cleaned"] is True
        assert results[0]["count_before"] == 1
        assert results[0]["count_after"] == 0

    def test_remove_by_socket_removes_all(self) -> None:
        """remove_by_socket removes all subscriptions for that socket."""
        results = run_ruby(SCRIPT, [
            {"action": "subscribe", "events": ["*"]},
            {"action": "subscribe", "events": ["entity_added"]},
            {"action": "status"},
            {"action": "remove_by_socket", "socket_index": 0},
            {"action": "status"},
        ])
        assert results[2]["subscriptions"] == 2
        assert results[4]["subscriptions"] == 1

    def test_chunk_format(self) -> None:
        """make_chunk produces hex-bytesize CRLF data CRLF format."""
        results = run_ruby(SCRIPT, [
            {"action": "make_chunk", "data": "hello"},
            {"action": "make_chunk", "data": ""},
        ])
        assert results[0]["chunk"] == "5\r\nhello\r\n"
        assert results[1]["chunk"] == "0\r\n\r\n"

    def test_status_counts(self) -> None:
        """Status returns version, model title, and subscription count."""
        results = run_ruby(SCRIPT, [
            {"action": "subscribe", "events": ["*"]},
            {"action": "subscribe", "events": ["entity_added"]},
            {"action": "status"},
        ])
        status = results[2]
        assert status["version"] == "1.0.0"
        assert isinstance(status["model"], str)
        assert status["subscriptions"] == 2

    def test_matches_star(self) -> None:
        """matches? with '*' returns true for any event."""
        results = run_ruby(SCRIPT, [
            {"action": "matches", "events": ["*"], "event": "entity_added"},
            {"action": "matches", "events": ["*"], "event": "entity_removed"},
        ])
        assert results[0]["result"] is True
        assert results[1]["result"] is True

    def test_matches_exact(self) -> None:
        """matches? with an exact name returns true for match, false for mismatch."""
        results = run_ruby(SCRIPT, [
            {"action": "matches", "events": ["entity_added"],
             "event": "entity_added"},
            {"action": "matches", "events": ["entity_added"],
             "event": "entity_modified"},
        ])
        assert results[0]["result"] is True
        assert results[1]["result"] is False

    def test_subscribe_with_multiple_events(self) -> None:
        """Subscribe with multiple events matches all of them."""
        results = run_ruby(SCRIPT, [
            {"action": "subscribe", "events": ["entity_added", "entity_modified"]},
            {"action": "dispatch", "event": "entity_added", "payload": {"v": 1}},
            {"action": "dispatch", "event": "entity_modified", "payload": {"v": 2}},
            {"action": "dispatch", "event": "entity_removed", "payload": {"v": 3}},
        ])
        assert len(results[1]["writes"]) == 1  # entity_added matched
        assert len(results[2]["writes"]) == 2  # entity_modified also matched
        assert len(results[3]["writes"]) == 2  # entity_removed did not match
