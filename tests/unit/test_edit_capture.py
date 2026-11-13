"""Unit tests for Blender-side edit capture (blender_plugin/edit_capture.py)."""

from blender_plugin.edit_capture import EditTracker

IDENT = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
MOVED = [1, 0, 0, 0.5, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
RED = (255, 0, 0)
BLUE = (0, 0, 255)


def test_unknown_id_is_not_an_edit():
    t = EditTracker()
    assert t.diff(42, MOVED, RED) is None


def test_unchanged_since_sync_is_not_an_edit():
    t = EditTracker()
    t.record_sync(42, IDENT, RED)
    assert t.diff(42, IDENT, RED) is None


def test_transform_change_is_reported():
    t = EditTracker()
    t.record_sync(42, IDENT, RED)
    e = t.diff(42, MOVED, RED)
    assert e is not None
    assert e.fields == {"transform"}
    assert e.transform == tuple(MOVED)
    assert e.color is None


def test_material_change_is_reported():
    t = EditTracker()
    t.record_sync(42, IDENT, RED)
    e = t.diff(42, IDENT, BLUE)
    assert e is not None
    assert e.fields == {"material"}
    assert e.color == BLUE
    assert e.transform is None


def test_both_fields_reported_together():
    t = EditTracker()
    t.record_sync(42, IDENT, RED)
    e = t.diff(42, MOVED, BLUE)
    assert e.fields == {"transform", "material"}


def test_echo_of_a_pushed_value_is_suppressed():
    """After a push succeeds we record it as synced; the snapshot that comes back
    matches, so it must not be re-queued as a new edit."""
    t = EditTracker()
    t.record_sync(42, IDENT, RED)
    t.record_sync(42, MOVED, RED)  # push succeeded
    assert t.diff(42, MOVED, RED) is None


def test_tiny_float_noise_is_not_an_edit():
    t = EditTracker()
    t.record_sync(42, IDENT, RED)
    noisy = [1, 0, 0, 1e-9, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    assert t.diff(42, noisy, RED) is None


def test_forget_stops_tracking():
    t = EditTracker()
    t.record_sync(42, IDENT, RED)
    t.forget(42)
    assert t.diff(42, MOVED, RED) is None


def test_none_color_is_handled():
    t = EditTracker()
    t.record_sync(42, IDENT, None)
    assert t.diff(42, IDENT, None) is None
    assert t.diff(42, IDENT, RED).fields == {"material"}


from blender_plugin.edit_capture import new_polygon_keys, removed_ids  # noqa: E402


def test_removed_ids_reports_tracked_ids_that_disappeared():
    assert removed_ids({1, 2, 3}, {1, 3}) == {2}


def test_removed_ids_ignores_new_ids():
    assert removed_ids({1}, {1, 2, 3}) == set()


def test_removed_ids_empty_when_nothing_tracked():
    assert removed_ids(set(), {1, 2}) == set()


def test_new_polygon_keys_are_the_difference():
    before = {((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))}
    after = before | {((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0))}
    assert new_polygon_keys(before, after) == after - before
    assert len(new_polygon_keys(before, after)) == 1


def test_no_new_polygons_when_unchanged():
    keys = {((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))}
    assert new_polygon_keys(keys, keys) == set()


def test_a_real_edit_just_above_the_tolerance_is_captured():
    """Pins the tolerance from both sides: float noise is ignored, but a real sub-millimetre move is an edit.

    The noise test alone would still pass if the tolerance were raised to a millimetre, which would silently
    stop small real edits from reaching SketchUp. A move of 10 * TOL (10 micrometres) must be captured.
    """
    from blender_plugin.edit_capture import TOL

    t = EditTracker()
    t.record_sync(42, IDENT, RED)
    nudged = [1, 0, 0, 10 * TOL, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    e = t.diff(42, nudged, RED)
    assert e is not None and "transform" in e.fields


def test_a_move_below_the_tolerance_is_not_an_edit():
    from blender_plugin.edit_capture import TOL

    t = EditTracker()
    t.record_sync(42, IDENT, RED)
    below = [1, 0, 0, TOL / 10, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    assert t.diff(42, below, RED) is None


def test_a_one_step_colour_change_is_captured():
    """Colour is 0-255 per channel, so the smallest real colour edit is one step on one channel.

    The shared TOL is a fraction of one step, so a one-step change must be captured; an identical colour must
    not. Without this, a tolerance widened to swallow a one-step change would pass every existing test.
    """
    t = EditTracker()
    t.record_sync(42, IDENT, RED)  # (255, 0, 0)
    one_step = (254, 0, 0)
    e = t.diff(42, IDENT, one_step)
    assert e is not None and "material" in e.fields and e.color == one_step


def test_an_identical_colour_is_not_an_edit():
    t = EditTracker()
    t.record_sync(42, IDENT, RED)
    assert t.diff(42, IDENT, (255, 0, 0)) is None


def test_forget_all_clears_every_tracked_id():
    """A fresh start must forget every tracked id, so a Blender-only wipe is not later read as user deletions.

    Without this, a scene emptied in Blender (a fresh start) leaves the tracker holding ids whose objects are gone,
    and the deletion pass then erases those objects in SketchUp. forget_all is the fresh-start reset.
    """
    t = EditTracker()
    t.record_sync(1, IDENT, RED)
    t.record_sync(2, IDENT, RED)
    t.forget_all()
    assert t._synced == {}
    assert removed_ids(set(), {1, 2}) == set()


def test_baseline_enrols_only_ids_sketchup_still_has():
    """The post-import baseline must not re-enrol a SketchUp id that no longer exists.

    An object can keep a deleted SketchUp id in Blender; after the deletion the import rebuilds the scene and the
    baseline would re-track that stale id, so the deletion would be undone in the tracker. Only ids the live
    snapshot reports are enrolled.
    """
    from blender_plugin.edit_capture import live_ids_to_enrol

    tagged = {558445: "erased", 558477: "kept", 558479: "kept"}
    live = {558477, 558479}
    assert live_ids_to_enrol(tagged.keys(), live) == {558477, 558479}
    assert live_ids_to_enrol({558445}, set()) == set()


def test_baseline_does_not_enrol_an_id_the_pass_is_about_to_delete():
    """An id the same pass deletes must not be enrolled by that pass's baseline.

    The deletion pass computes removed_ids from the tracker, then the import baseline runs. If the baseline enrols
    an id the pass is removing (still listed by the snapshot it filters against), the erasure is undone in the
    tracker. The baseline must skip ids the pass is removing.
    """
    from blender_plugin.edit_capture import live_ids_to_enrol_excluding_removed

    live = {10, 20}
    removing = {20}
    assert live_ids_to_enrol_excluding_removed(live, removing) == {10}
    assert live_ids_to_enrol_excluding_removed(live, set()) == {10, 20}


def test_baseline_after_a_deletion_does_not_re_enrol_the_forgotten_id():
    """A baseline that runs after a deletion pass must not re-track an id that pass forgot.

    The deletion loop forgets ids SketchUp has erased; the post-import baseline runs later in the same pass and its
    snapshot still lists them. The baseline must exclude this pass's forgotten ids.
    """
    from blender_plugin.edit_capture import EditTracker

    t = EditTracker()
    t.record_sync(7, IDENT, RED)
    t.forget(7)
    assert t.forgotten_this_pass() == {7}
    # the baseline's admission is the snapshot's live ids minus what this pass forgot
    admitted = {7} - t.forgotten_this_pass()
    assert admitted == set()
    # a new pass clears the mark
    t.begin_pass()
    assert t.forgotten_this_pass() == set()
