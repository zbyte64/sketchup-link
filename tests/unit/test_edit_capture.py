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
