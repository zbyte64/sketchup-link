"""
sync_push.py: push Blender edits to SketchUp through the control routes.

Milestone 1 of the Blender -> SketchUp sync (docs/design/blender-to-sketchup-sync.md).

Conflict policy (decided): SketchUp wins, with a visible warning. Before pushing an edit
we read the current SketchUp value. If SketchUp changed since our last sync, SketchUp's
value stands, the Blender edit is dropped, and the user is warned which object was
overwritten. Only when SketchUp still matches our last-synced baseline is the Blender
edit sent.

The decision logic is pure Python so it is unit-testable. The HTTP calls are injected,
so the unit tests use fakes and the live tests use the real control routes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .edit_capture import Edit, _close_color, _close_matrix


@dataclass
class PushResult:
    persistent_id: int
    pushed: list = field(default_factory=list)      # fields successfully pushed
    overwritten: list = field(default_factory=list)  # fields SketchUp changed; Blender edit dropped
    error: str | None = None


@dataclass
class SketchUpState:
    """The current SketchUp value for one object, as read from the live snapshot."""

    transform: tuple | None = None
    color: tuple | None = None


def decide(edit: Edit, baseline, current: SketchUpState) -> PushResult:
    """Decide which parts of an edit to push, given SketchUp's current value.

    baseline: the last-synced SyncedState for this object (what both sides agreed on).
    current:  SketchUp's value now.
    """
    result = PushResult(persistent_id=edit.persistent_id)
    for field_name in sorted(edit.fields):
        if field_name == "transform":
            unchanged = _close_matrix(current.transform, baseline.transform)
            if unchanged:
                result.pushed.append("transform")
            else:
                result.overwritten.append("transform")
        elif field_name == "material":
            unchanged = _close_color(current.color, baseline.color)
            if unchanged:
                result.pushed.append("material")
            else:
                result.overwritten.append("material")
    return result


def push(
    edit: Edit,
    baseline,
    read_current: Callable[[int], SketchUpState],
    send_transform: Callable[[int, tuple], int],
    send_material: Callable[[str, tuple], int],
    material_name_for: Callable[[int], str | None],
) -> PushResult:
    """Read SketchUp's current value, decide, and send only the parts that still apply.

    send_* return the HTTP status code of the control call.
    """
    current = read_current(edit.persistent_id)
    result = decide(edit, baseline, current)

    if "transform" in result.pushed and edit.transform is not None:
        status = send_transform(edit.persistent_id, edit.transform)
        if status != 200:
            result.error = f"transform push failed: HTTP {status}"
            result.pushed.remove("transform")

    if "material" in result.pushed and edit.color is not None:
        name = material_name_for(edit.persistent_id)
        if name is None:
            result.error = (result.error or "") + " material push skipped: no material name"
            result.pushed.remove("material")
        else:
            status = send_material(name, edit.color)
            if status != 200:
                result.error = (result.error or "") + f" material push failed: HTTP {status}"
                result.pushed.remove("material")

    return result


def warning_text(result: PushResult) -> str | None:
    """A user-facing warning for any edit SketchUp overwrote, or None."""
    if not result.overwritten:
        return None
    what = " and ".join(result.overwritten)
    return (f"SketchUp changed object {result.persistent_id} since your last sync; "
            f"your Blender {what} edit was discarded (SketchUp wins).")


# ---------------------------------------------------------------------------
# User-visible warnings. A dropped edit must not vanish silently: it is kept here
# until the user dismisses it, and shown in the Blender panel.
# ---------------------------------------------------------------------------

_warnings: list[str] = []
MAX_WARNINGS = 20


def may_push_edits(two_way_enabled) -> bool:
    """Whether Blender edits may be pushed into SketchUp. Two-way editing is a toggle set in SketchUp.

    Off unless explicitly enabled: a missing or unknown setting (None) keeps it off, so the default is SketchUp wins
    and Blender edits are only reported, not written back.
    """
    return two_way_enabled is True


def conflict_warning(obj_name: str, stale: bool) -> str:
    """The sync warning for an imported object's edit that could not be pushed.

    stale=True: SketchUp changed the same face since the Blender edit, so the edit is dropped (SketchUp wins).
    Saying so matters: 'kept in Blender only' would mislead, since the edit is not kept.
    """
    if stale:
        return (f"{obj_name}: SketchUp changed this face since your edit, so your edit was dropped "
                f"(SketchUp wins). Re-make the edit on the current face if you still want it.")
    return f"{obj_name}: vertex edit could not be pushed to SketchUp, kept in Blender only"


def add_warning(text: str) -> None:
    """Record a warning, keeping the most recent MAX_WARNINGS."""
    _warnings.append(text)
    del _warnings[:-MAX_WARNINGS]


def warnings() -> list[str]:
    return list(_warnings)


def clear_warnings() -> None:
    _warnings.clear()


def record_result(result: PushResult) -> None:
    """Turn a push result into a user warning when SketchUp overwrote an edit."""
    text = warning_text(result)
    if text is not None:
        add_warning(text)
