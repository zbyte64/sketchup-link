"""Unit tests for the push decision and the SketchUp-wins conflict policy."""

from blender_plugin.edit_capture import Edit, SyncedState
from blender_plugin.sync_push import SketchUpState, decide, push, warning_text

IDENT = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
MOVED = (1, 0, 0, 0.5, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
RED = (255, 0, 0)
BLUE = (0, 0, 255)
BASE = SyncedState(transform=IDENT, color=RED)


def test_unchanged_in_sketchup_pushes_transform():
    e = Edit(42, transform=MOVED, fields={"transform"})
    r = decide(e, BASE, SketchUpState(transform=IDENT, color=RED))
    assert r.pushed == ["transform"] and r.overwritten == []


def test_sketchup_changed_transform_is_overwritten_not_pushed():
    e = Edit(42, transform=MOVED, fields={"transform"})
    r = decide(e, BASE, SketchUpState(transform=(1, 0, 0, 2.0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1), color=RED))
    assert r.pushed == [] and r.overwritten == ["transform"]


def test_material_conflict_is_detected_independently_of_transform():
    e = Edit(42, transform=MOVED, color=BLUE, fields={"transform", "material"})
    r = decide(e, BASE, SketchUpState(transform=IDENT, color=(0, 255, 0)))
    assert r.pushed == ["transform"] and r.overwritten == ["material"]


def test_push_sends_only_the_unconflicted_fields():
    sent = {"t": [], "m": []}
    e = Edit(42, transform=MOVED, color=BLUE, fields={"transform", "material"})
    r = push(
        e, BASE,
        read_current=lambda pid: SketchUpState(transform=IDENT, color=(0, 255, 0)),
        send_transform=lambda pid, t: sent["t"].append((pid, t)) or 200,
        send_material=lambda n, c: sent["m"].append((n, c)) or 200,
        material_name_for=lambda pid: "Red",
    )
    assert sent["t"] == [(42, MOVED)]
    assert sent["m"] == []  # material conflicted with SketchUp, so not sent
    assert r.overwritten == ["material"]


def test_failed_control_call_is_reported_not_swallowed():
    e = Edit(42, transform=MOVED, fields={"transform"})
    r = push(
        e, BASE,
        read_current=lambda pid: SketchUpState(transform=IDENT, color=RED),
        send_transform=lambda pid, t: 500,
        send_material=lambda n, c: 200,
        material_name_for=lambda pid: None,
    )
    assert r.pushed == []
    assert r.error is not None and "transform push failed: HTTP 500" in r.error


def test_warning_names_the_object_and_field():
    e = Edit(42, transform=MOVED, fields={"transform"})
    r = decide(e, BASE, SketchUpState(transform=(1, 0, 0, 9.0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1), color=RED))
    w = warning_text(r)
    assert w is not None and "42" in w and "transform" in w and "SketchUp wins" in w


def test_no_warning_when_nothing_was_overwritten():
    e = Edit(42, transform=MOVED, fields={"transform"})
    r = decide(e, BASE, SketchUpState(transform=IDENT, color=RED))
    assert warning_text(r) is None


def test_record_result_keeps_overwritten_edit_as_a_warning():
    from blender_plugin import sync_push
    sync_push.clear_warnings()
    e = Edit(42, transform=MOVED, fields={"transform"})
    r = decide(e, BASE, SketchUpState(transform=(1, 0, 0, 9.0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1), color=RED))
    sync_push.record_result(r)
    assert len(sync_push.warnings()) == 1
    assert "42" in sync_push.warnings()[0]
    sync_push.clear_warnings()


def test_clean_push_adds_no_warning():
    from blender_plugin import sync_push
    sync_push.clear_warnings()
    e = Edit(42, transform=MOVED, fields={"transform"})
    sync_push.record_result(decide(e, BASE, SketchUpState(transform=IDENT, color=RED)))
    assert sync_push.warnings() == []


def test_warnings_are_capped_at_the_most_recent():
    from blender_plugin import sync_push
    sync_push.clear_warnings()
    for i in range(sync_push.MAX_WARNINGS + 5):
        sync_push.add_warning(f"w{i}")
    kept = sync_push.warnings()
    assert len(kept) == sync_push.MAX_WARNINGS
    assert kept[-1] == f"w{sync_push.MAX_WARNINGS + 4}"
    sync_push.clear_warnings()
