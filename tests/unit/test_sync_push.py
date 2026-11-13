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


def test_conflict_message_names_the_other_side_change():
    """A face SketchUp changed since the Blender edit is a conflict, and the warning must say so.

    Before: the user saw 'vertex edit kept in Blender only', which is false: the edit was dropped, and nothing
    told them SketchUp had changed the same face. A conflict message names that cause.
    """
    import blender_plugin.sync_push as sp

    msg = sp.conflict_warning("Loose Entity", stale=True)
    assert "SketchUp changed" in msg and "dropped" in msg
    assert "kept in Blender" not in msg


def test_generic_push_failure_keeps_the_plain_message():
    import blender_plugin.sync_push as sp

    msg = sp.conflict_warning("Loose Entity", stale=False)
    assert "could not be pushed" in msg
    assert "SketchUp changed" not in msg


def test_a_skipped_error_entity_is_reported_to_the_user():
    """An entity SketchUp could not serialize arrives as {type: 'Error'} and is dropped from the Blender model.

    The drop must be visible to the Blender user, not only in SketchUp's log: a model missing a part with no
    warning looks complete. Reporting it is the adapter's job, since it is where the entity is filtered.
    """
    from blender_plugin.live_adapter import skipped_entity_warnings

    snap_entities = [
        {"type": "Face", "persistent_id": 1, "outer_loop": []},
        {"type": "Error", "message": "boom", "persistent_id": None},
    ]
    warnings = skipped_entity_warnings(snap_entities)
    assert len(warnings) == 1
    assert "could not be read" in warnings[0] and "boom" in warnings[0]


def test_no_warning_when_every_entity_is_understood():
    from blender_plugin.live_adapter import skipped_entity_warnings

    assert skipped_entity_warnings([{"type": "Face", "persistent_id": 1, "outer_loop": []}]) == []


def test_an_error_with_no_message_still_gives_a_readable_warning():
    """An Error entry whose message is empty must still produce a sensible warning, never a bare blank.

    The adapter falls back to 'unknown error' so the user is told something failed even when SketchUp gave no
    reason. This pins that fallback, which had no coverage.
    """
    from blender_plugin.live_adapter import skipped_entity_warnings

    warnings = skipped_entity_warnings([{"type": "Error", "message": "", "persistent_id": None}])
    assert len(warnings) == 1
    assert "unknown error" in warnings[0]


def test_a_mesh_present_at_the_baseline_is_not_new_geometry():
    """Untagged scene objects present when sync starts (the factory Cube, or any object the user did not add
    during this session) are not new geometry and must not be pushed into SketchUp.

    The repo's own intent: untagged objects are user data, never sync data (scene_importer 'Untagged user data is
    never touched'; live_timer_stale_snapshot 'the timer would push [the factory Cube] as new geometry' is the
    defect). Only objects added after the baseline are new geometry.
    """
    from blender_plugin.edit_capture import new_geometry_candidates

    baseline = {"Cube", "Camera", "Light"}
    now = {"Cube", "Camera", "Light", "MyNewBox"}
    assert new_geometry_candidates(now, baseline) == {"MyNewBox"}
    assert new_geometry_candidates(baseline, baseline) == set()


def test_first_pass_baseline_is_set_before_any_push():
    """On the first sync pass the baseline must already name the scene's existing objects.

    The push runs in the same timer pass as the import. If the baseline is still empty then (it is only recorded
    after the import), every untagged scene object (the factory Cube) looks newly added and is pushed into SketchUp.
    The baseline must be taken before the push decision, so the factory Cube is never new geometry.
    """
    from blender_plugin.edit_capture import new_geometry_candidates, set_baseline_for_first_pass

    scene = {"Cube", "Camera"}
    set_baseline_for_first_pass(scene)
    assert new_geometry_candidates(scene, set_baseline_for_first_pass.__globals__["_baseline_names"]) == set()


def test_two_way_editing_is_off_by_default_and_blocks_pushes():
    """Two-way editing (Blender edits pushed into SketchUp) sits behind a toggle set in SketchUp.

    With the toggle off, no Blender edit is pushed; the sync keeps SketchUp's state and only reports what it would
    have changed. With it on, edits are pushed as before. Off is the default.
    """
    from blender_plugin.sync_push import may_push_edits

    assert may_push_edits(two_way_enabled=False) is False
    assert may_push_edits(two_way_enabled=True) is True
    assert may_push_edits(two_way_enabled=None) is False
