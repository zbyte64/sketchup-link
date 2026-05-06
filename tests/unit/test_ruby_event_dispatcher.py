"""Tests for EventDispatcher via Ruby subprocess.

Uses event_dispatcher_test.rb helper which accepts an array of command objects
and returns {"commands": [...], "events": [...], "timers": N}.
"""

from __future__ import annotations

import pytest

from tests.unit.conftest import run_ruby


SCRIPT = "event_dispatcher_test.rb"


def _run(commands: list[dict]) -> dict:
    """Send commands array to the Ruby helper and return the full result."""
    return run_ruby(SCRIPT, commands)


# ---------------------------------------------------------------------------
# Transaction batching
# ---------------------------------------------------------------------------


class TestTransactionBatching:
    """Entities added/modified inside transactions are batched."""

    @pytest.mark.ruby
    def test_transaction_batching_added(self):
        """Entities added inside a transaction are batched, not dispatched until commit."""
        result = _run([
            {"action": "create"},
            {"action": "transaction_start"},
            {"action": "entity_added", "entity": {"persistent_id": 1}},
            {"action": "get_events"},
            {"action": "set_model", "model": {"guid": "m1", "title": "T"}},
            {"action": "transaction_commit"},
            {"action": "get_events"},
        ])
        # No events while transaction is open
        assert len(result["commands"][3]["events"]) == 0

        # One commit event after commit
        events = result["commands"][6]["events"]
        assert len(events) == 1
        ev = events[0]
        assert ev["event"] == "transaction.commit"
        assert len(ev["payload"]["data"]["added"]) == 1
        assert ev["payload"]["data"]["added"][0]["persistent_id"] == 1

    @pytest.mark.ruby
    def test_transaction_dedup_added(self):
        """Same entity added twice in a transaction is deduplicated by persistent_id."""
        result = _run([
            {"action": "create"},
            {"action": "transaction_start"},
            {"action": "entity_added", "entity": {"persistent_id": 1}},
            {"action": "entity_added", "entity": {"persistent_id": 1}},
            {"action": "set_model", "model": {"guid": "m1", "title": "T"}},
            {"action": "transaction_commit"},
            {"action": "get_events"},
        ])
        events = result["commands"][6]["events"]
        assert len(events) == 1
        assert len(events[0]["payload"]["data"]["added"]) == 1

    @pytest.mark.ruby
    def test_transaction_commit_dispatches(self):
        """On commit with a non-empty batch, an event is dispatched."""
        result = _run([
            {"action": "create"},
            {"action": "transaction_start"},
            {"action": "entity_added", "entity": {"persistent_id": 1}},
            {"action": "set_model", "model": {"guid": "m1", "title": "T"}},
            {"action": "transaction_commit"},
            {"action": "get_events"},
        ])
        events = result["commands"][5]["events"]
        assert len(events) == 1
        assert events[0]["event"] == "transaction.commit"

    @pytest.mark.ruby
    def test_transaction_commit_empty_batch_skips(self):
        """On commit with an empty batch, no dispatch occurs."""
        result = _run([
            {"action": "create"},
            {"action": "transaction_start"},
            {"action": "set_model", "model": {"guid": "m1", "title": "T"}},
            {"action": "transaction_commit"},
            {"action": "get_events"},
        ])
        assert len(result["commands"][4]["events"]) == 0

    @pytest.mark.ruby
    def test_transaction_abort_resets_batch(self):
        """On abort, the batch is cleared and no dispatch occurs."""
        result = _run([
            {"action": "create"},
            {"action": "transaction_start"},
            {"action": "entity_added", "entity": {"persistent_id": 1}},
            {"action": "transaction_abort"},
            {"action": "get_events"},
        ])
        assert len(result["commands"][4]["events"]) == 0

    @pytest.mark.ruby
    def test_transaction_undo_dispatches(self):
        """Undo resets the batch and dispatches EVT_TRANSACTION_UNDO."""
        result = _run([
            {"action": "create"},
            {"action": "set_model", "model": {"guid": "m1", "title": "T"}},
            {"action": "transaction_undo"},
            {"action": "get_events"},
        ])
        events = result["commands"][3]["events"]
        assert len(events) == 1
        assert events[0]["event"] == "transaction.undo"
        assert events[0]["payload"]["data"]["model_guid"] == "m1"

    @pytest.mark.ruby
    def test_transaction_redo_dispatches(self):
        """Redo resets the batch and dispatches EVT_TRANSACTION_REDO."""
        result = _run([
            {"action": "create"},
            {"action": "set_model", "model": {"guid": "m1", "title": "T"}},
            {"action": "transaction_redo"},
            {"action": "get_events"},
        ])
        events = result["commands"][3]["events"]
        assert len(events) == 1
        assert events[0]["event"] == "transaction.redo"
        assert events[0]["payload"]["data"]["model_guid"] == "m1"

    @pytest.mark.ruby
    def test_nested_transactions(self):
        """Two levels deep; inner commit does not dispatch, outer commit does."""
        result = _run([
            {"action": "create"},
            # Nested start
            {"action": "transaction_start"},
            {"action": "transaction_start"},
            {"action": "entity_added", "entity": {"persistent_id": 1}},
            # Inner commit — depth still > 0, no dispatch
            {"action": "get_events"},
            {"action": "set_model", "model": {"guid": "m1", "title": "T"}},
            {"action": "transaction_commit"},
            {"action": "get_events"},
            # Outer commit — depth reaches 0, dispatch
            {"action": "set_model", "model": {"guid": "m1", "title": "T"}},
            {"action": "transaction_commit"},
            {"action": "get_events"},
        ])
        # After inner commit — depth still 1
        assert len(result["commands"][4]["events"]) == 0
        # After inner commit (second check) — still no dispatch
        assert len(result["commands"][7]["events"]) == 0
        # After outer commit — dispatched
        events = result["commands"][10]["events"]
        assert len(events) == 1
        assert events[0]["event"] == "transaction.commit"
        assert len(events[0]["payload"]["data"]["added"]) == 1

    @pytest.mark.ruby
    def test_multiple_entities_added_inside_transaction(self):
        """Multiple unique entities added inside a transaction are all batched."""
        result = _run([
            {"action": "create"},
            {"action": "transaction_start"},
            {"action": "entity_added", "entity": {"persistent_id": 1}},
            {"action": "entity_added", "entity": {"persistent_id": 2}},
            {"action": "entity_added", "entity": {"persistent_id": 3}},
            {"action": "set_model", "model": {"guid": "m1", "title": "T"}},
            {"action": "transaction_commit"},
            {"action": "get_events"},
        ])
        events = result["commands"][7]["events"]
        assert len(events) == 1
        data = events[0]["payload"]["data"]
        assert len(data["added"]) == 3
        pids = {e["persistent_id"] for e in data["added"]}
        assert pids == {1, 2, 3}


# ---------------------------------------------------------------------------
# Debounce behavior
# ---------------------------------------------------------------------------


class TestDebounce:
    """Direct (un-transacted) entity edits are debounced via timer."""

    @pytest.mark.ruby
    def test_debounce_fires_after_interval(self):
        """Direct entity edit starts a timer; after running timers, the event fires."""
        result = _run([
            {"action": "create"},
            {"action": "entity_modified", "entity": {"persistent_id": 1}},
            {"action": "get_timers"},
            {"action": "run_timers"},
            {"action": "get_events"},
        ])
        assert result["commands"][2]["timer_count"] == 1
        events = result["commands"][4]["events"]
        assert len(events) == 1
        assert events[0]["event"] == "transaction.commit"
        assert len(events[0]["payload"]["data"]["modified"]) == 1

    @pytest.mark.ruby
    def test_debounce_cancelled_on_new_event(self):
        """A second edit cancels the first timer; only one dispatch occurs."""
        result = _run([
            {"action": "create"},
            {"action": "entity_modified", "entity": {"persistent_id": 1}},
            # Second edit resets the timer
            {"action": "entity_modified", "entity": {"persistent_id": 1}},
            {"action": "get_timers"},
            {"action": "run_timers"},
            {"action": "get_events"},
        ])
        assert result["commands"][3]["timer_count"] == 1
        events = result["commands"][5]["events"]
        assert len(events) == 1

    @pytest.mark.ruby
    def test_debounce_cancelled_on_transaction_start(self):
        """A direct-edit debounce is cancelled when a transaction starts."""
        result = _run([
            {"action": "create"},
            {"action": "entity_modified", "entity": {"persistent_id": 1}},
            {"action": "transaction_start"},
            {"action": "get_timers"},
        ])
        assert result["commands"][3]["timer_count"] == 0


# ---------------------------------------------------------------------------
# Entity validation
# ---------------------------------------------------------------------------


class TestEntityValidation:
    """Invalid entities are skipped during batching."""

    @pytest.mark.ruby
    def test_entity_added_invalid_skipped(self):
        """An entity with valid?=false is not added to the batch."""
        result = _run([
            {"action": "create"},
            {"action": "transaction_start"},
            {"action": "entity_added", "entity": {"persistent_id": 1, "valid": False}},
            {"action": "set_model", "model": {"guid": "m1", "title": "T"}},
            {"action": "transaction_commit"},
            {"action": "get_events"},
        ])
        assert len(result["commands"][5]["events"]) == 0


# ---------------------------------------------------------------------------
# Immediate events (selection, materials, layers)
# ---------------------------------------------------------------------------


class TestImmediateEvents:
    """Selection, materials, and layers changes dispatch immediately."""

    @pytest.mark.ruby
    def test_selection_change_immediate(self):
        """on_selection_change dispatches immediately."""
        result = _run([
            {"action": "create"},
            {"action": "set_model", "model": {"guid": "m1", "title": "T"}},
            {"action": "selection_change"},
            {"action": "get_events"},
        ])
        events = result["commands"][3]["events"]
        assert len(events) == 1
        assert events[0]["event"] == "selection.change"

    @pytest.mark.ruby
    def test_materials_change_immediate(self):
        """on_materials_change dispatches immediately."""
        result = _run([
            {"action": "create"},
            {"action": "set_model", "model": {"guid": "m1", "title": "T"}},
            {"action": "materials_change"},
            {"action": "get_events"},
        ])
        events = result["commands"][3]["events"]
        assert len(events) == 1
        assert events[0]["event"] == "materials.change"

    @pytest.mark.ruby
    def test_layers_change_immediate(self):
        """on_layers_change dispatches immediately."""
        result = _run([
            {"action": "create"},
            {"action": "set_model", "model": {"guid": "m1", "title": "T"}},
            {"action": "layers_change"},
            {"action": "get_events"},
        ])
        events = result["commands"][3]["events"]
        assert len(events) == 1
        assert events[0]["event"] == "layers.change"


# ---------------------------------------------------------------------------
# Envelope format
# ---------------------------------------------------------------------------


class TestEnvelope:
    """Dispatched events conform to the standard envelope format."""

    @pytest.mark.ruby
    def test_envelope_format(self):
        """A dispatched event has event, timestamp, and data keys."""
        result = _run([
            {"action": "create"},
            {"action": "set_model", "model": {"guid": "m1", "title": "T"}},
            {"action": "selection_change"},
            {"action": "get_events"},
        ])
        events = result["commands"][3]["events"]
        assert len(events) == 1
        ev = events[0]
        assert "event" in ev
        assert "payload" in ev
        payload = ev["payload"]
        assert "event" in payload
        assert "timestamp" in payload
        assert isinstance(payload["timestamp"], float)
        assert "data" in payload


# ---------------------------------------------------------------------------
# Model lifecycle events
# ---------------------------------------------------------------------------


class TestModelLifecycle:
    """Model save, open, and close dispatch immediately."""

    @pytest.mark.ruby
    def test_model_save_dispatches(self):
        """Model save dispatches EVT_MODEL_SAVE."""
        result = _run([
            {"action": "create"},
            {"action": "set_model", "model": {"guid": "m1", "title": "T"}},
            {"action": "model_save"},
            {"action": "get_events"},
        ])
        events = result["commands"][3]["events"]
        assert len(events) == 1
        assert events[0]["event"] == "model.save"

    @pytest.mark.ruby
    def test_model_open_dispatches(self):
        """Model open dispatches EVT_MODEL_OPEN."""
        result = _run([
            {"action": "create"},
            {"action": "set_model", "model": {"guid": "m1", "title": "T"}},
            {"action": "model_open"},
            {"action": "get_events"},
        ])
        events = result["commands"][3]["events"]
        assert len(events) == 1
        assert events[0]["event"] == "model.open"

    @pytest.mark.ruby
    def test_model_close_dispatches(self):
        """Model close dispatches EVT_MODEL_CLOSE."""
        result = _run([
            {"action": "create"},
            {"action": "set_model", "model": {"guid": "m1", "title": "T"}},
            {"action": "model_close"},
            {"action": "get_events"},
        ])
        events = result["commands"][3]["events"]
        assert len(events) == 1
        assert events[0]["event"] == "model.close"
