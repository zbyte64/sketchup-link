"""
edit_capture.py: detect Blender-side edits to objects imported from SketchUp.

Milestone 1 of the Blender -> SketchUp sync (docs/design/blender-to-sketchup-sync.md).

The importer stamps each object it creates from a SketchUp group or instance with
`skp_persistent_id`. We remember the last value we wrote for each such object (its
transform and its material colour). A change is an edit only when the current value
differs from that last-synced value. Comparing against the last-synced value, rather
than "anything changed", is what stops a pushed change from echoing back as a new edit.

The comparison is pure Python so it is unit-testable without Blender. The Blender
depsgraph handler is a thin wrapper around it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

ID_PROP = "skp_persistent_id"
TOL = 1e-6


def _close_matrix(a, b, tol=TOL):
    """True when two flat 16-element transforms are equal within tol."""
    if a is None or b is None:
        return a is b
    return len(a) == len(b) and all(math.isclose(x, y, abs_tol=tol) for x, y in zip(a, b))


def _close_color(a, b, tol=TOL):
    if a is None or b is None:
        return a is b
    return len(a) == len(b) and all(math.isclose(x, y, abs_tol=tol) for x, y in zip(a, b))


@dataclass
class SyncedState:
    """What we last wrote to SketchUp (or imported from it) for one object."""

    transform: tuple | None = None  # flat row-major 16 floats, metres
    color: tuple | None = None      # (r, g, b) 0-255, or None when unmaterialled


@dataclass
class Edit:
    persistent_id: int
    transform: tuple | None = None
    color: tuple | None = None
    fields: set = field(default_factory=set)  # {"transform", "material"}


class EditTracker:
    """Keeps last-synced state per SketchUp id and reports real differences."""

    def __init__(self):
        self._synced: dict[int, SyncedState] = {}

    def record_sync(self, persistent_id: int, transform, color) -> None:
        """Record a value that is now the agreed state (imported, or pushed successfully)."""
        self._synced[int(persistent_id)] = SyncedState(
            transform=tuple(transform) if transform is not None else None,
            color=tuple(color) if color is not None else None,
        )

    def forget(self, persistent_id: int) -> None:
        self._synced.pop(int(persistent_id), None)

    def diff(self, persistent_id: int, transform, color) -> Edit | None:
        """Return an Edit describing what changed since the last sync, or None.

        A never-synced id is not an edit (we cannot tell a change from the import itself),
        so it is skipped.
        """
        pid = int(persistent_id)
        last = self._synced.get(pid)
        if last is None:
            return None
        cur_t = tuple(transform) if transform is not None else None
        cur_c = tuple(color) if color is not None else None
        changed = set()
        if not _close_matrix(cur_t, last.transform):
            changed.add("transform")
        if not _close_color(cur_c, last.color):
            changed.add("material")
        if not changed:
            return None
        return Edit(
            persistent_id=pid,
            transform=cur_t if "transform" in changed else None,
            color=cur_c if "material" in changed else None,
            fields=changed,
        )


# ---------------------------------------------------------------------------
# Blender wiring. Imported lazily so the pure comparison above stays testable
# without Blender installed.
# ---------------------------------------------------------------------------

_tracker = EditTracker()
_pending: dict[int, Edit] = {}


def tracker() -> EditTracker:
    return _tracker


def pending_edits() -> list[Edit]:
    """Edits captured since the last drain, one per SketchUp id (latest wins)."""
    return list(_pending.values())


def drain_pending() -> list[Edit]:
    edits = list(_pending.values())
    _pending.clear()
    return edits


def _object_transform(ob) -> tuple:
    # matrix_basis is the object's own transform and updates as soon as a property is set.
    # matrix_world is only recomputed when the depsgraph re-evaluates, so reading it here
    # would miss an edit that has just happened.
    return tuple(v for row in ob.matrix_basis for v in row)


def _object_color(ob) -> tuple | None:
    """Diffuse colour of the object's first material as 0-255 RGB, or None."""
    if not ob.material_slots:
        return None
    mat = ob.material_slots[0].material
    if mat is None:
        return None
    c = mat.diffuse_color
    return (round(c[0] * 255), round(c[1] * 255), round(c[2] * 255))


def on_depsgraph_update(scene, depsgraph=None):  # pragma: no cover - needs Blender
    """bpy.app.handlers.depsgraph_update_post callback.

    Only objects the importer tagged with skp_persistent_id are considered. A change is
    queued only when it differs from the last-synced value, so an import does not look
    like an edit.
    """
    import bpy  # type: ignore[import-not-found]  # Blender-only module

    for ob in bpy.data.objects:
        if ID_PROP not in ob:
            continue
        pid = int(ob[ID_PROP])
        edit = _tracker.diff(pid, _object_transform(ob), _object_color(ob))
        if edit is not None:
            _pending[pid] = edit


def record_import_state() -> None:  # pragma: no cover - needs Blender
    """Record every tagged object's current state as the synced baseline.

    Called after an import so the import itself is never reported as an edit.
    """
    import bpy  # type: ignore[import-not-found]  # Blender-only module

    _set_baseline_names({o.name for o in bpy.data.objects})
    for ob in bpy.data.objects:
        if ID_PROP in ob:
            _tracker.record_sync(int(ob[ID_PROP]), _object_transform(ob), _object_color(ob))


# ---------------------------------------------------------------------------
# Structural edits (milestone 2): deletes and adds. Pure, so they are unit-testable.
# ---------------------------------------------------------------------------

# The object names present when the sync baseline was taken. Set by record_import_state (called after each import),
# so anything the user adds afterwards is distinguishable from what was already in the scene.
_baseline_names: set[str] = set()


def sync_baseline_names() -> set[str]:
    return set(_baseline_names)


def _set_baseline_names(names) -> None:
    global _baseline_names
    _baseline_names = set(names)


def new_geometry_candidates(now: set[str], baseline: set[str]) -> set[str]:
    """Object names that were added after the sync baseline: the only objects that are new user geometry.

    Anything already present when sync started (the factory Cube, or any other scene object the user did not add
    this session) is scene scaffolding, not sync data, and must never be pushed into SketchUp.
    """
    return set(now) - set(baseline)


def removed_ids(tracked: set[int], present: set[int]) -> set[int]:
    """Ids the tracker knows about that no longer exist in Blender: deletions made in Blender.

    A deleted object is never seen by the depsgraph handler (it no longer exists), so its
    absence is the only signal. An id is removed only if it was tracked and is now missing.
    """
    return {int(pid) for pid in tracked} - {int(pid) for pid in present}


def new_polygon_keys(before: set[tuple], after: set[tuple]) -> set[tuple]:
    """Polygons added in Blender, keyed by their vertex coordinates (rounded).

    A polygon has no SketchUp id until it is pushed, so identity is its geometry. Keys are
    tuples of rounded (x, y, z) per vertex, made order-independent by sorting.
    """
    return after - before
