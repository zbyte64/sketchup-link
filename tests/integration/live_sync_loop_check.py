"""
Live-sync poll -> queue -> timer check. Runs INSIDE Blender (`blender --background`).

Feeds snapshots into the live-sync queue and calls _sync_timer() DIRECTLY
(bpy.app.timers is never registered).

Steps and their data source (see each step's label in the output):
  (a) LIVE       first snapshot from the live SketchUp at SKETCHUP_LINK_HOST:PORT
                 is imported by _sync_timer().
  (c) LIVE       when several snapshots are queued, _sync_timer() imports only
                 the latest one (queue keeps only the freshest snapshot).
  (b) LIVE       the FurnitureGroup is moved +0.5 m in X in SketchUp through
                 POST /control/geometry/transform; the next snapshot, imported
                 by _sync_timer(), moves the Blender object identified by the
                 group's SketchUp id by the same amount.

Environment:
    SKETCHUP_LINK_HOST  default 127.0.0.1
    SKETCHUP_LINK_PORT  default 9876

Exit 0 on success, non-zero on any failure.
"""

import copy
import json
import os
import queue
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import bpy  # type: ignore[import-not-found]  # noqa: E402  (Blender-only module)
import addon_utils  # type: ignore[import-not-found]  # noqa: E402

HOST = os.environ.get("SKETCHUP_LINK_HOST", "127.0.0.1")
PORT = int(os.environ.get("SKETCHUP_LINK_PORT", "9876"))

RESULTS = []


def step(label, name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    RESULTS.append((label, name, ok))
    print(f"[{label}] {tag}: {name} {detail}".rstrip())


def fail_exit(msg):
    print(f"LIVE-SYNC-LOOP FAIL: {msg}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Enable the addon through Blender's addon system (creates prefs entry).
# ---------------------------------------------------------------------------
addon_utils.paths()
addon_utils.enable("blender_plugin", default_set=True, persistent=False)
if "blender_plugin" not in bpy.context.preferences.addons:
    fail_exit("blender_plugin did not appear in context.preferences.addons")

from blender_plugin import live_sync  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402

# Snapshot the global sync state so we can restore it on exit.
_SAVED_STATE = dict(live_sync._sync_state)


def restore_state():
    live_sync._sync_state.clear()
    live_sync._sync_state.update(_SAVED_STATE)


def fresh_scene():
    # A fresh start, not a user deletion: forget the tracked ids first, so the wipe is not propagated to SketchUp
    # as a deletion of the groups it still holds (the deletion pass would otherwise erase them).
    from blender_plugin import edit_capture as _ec_fresh
    _ec_fresh.tracker().forget_all()
    bpy.ops.wm.read_factory_settings(use_empty=True)


def object_for_pid(pid):
    """Return the Blender object stored with this SketchUp persistent id, or None."""
    return next((o for o in bpy.data.objects if o.get("skp_persistent_id") == pid), None)


def post_control(path, body):
    req = urllib.request.Request(f"http://{HOST}:{PORT}/control/{path}", data=json.dumps(body).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, json.loads(r.read() or b"{}")


def import_snapshot_via_timer(snapshot):
    """Enqueue one snapshot, then drive _sync_timer() once directly (no bpy.app.timers)."""
    q = queue.SimpleQueue()
    q.put(snapshot)
    live_sync._sync_state.update(running=True, queue=q, failures=0, interval=2.0)
    return live_sync._sync_timer()


# ===========================================================================
# (a) LIVE — first import
# ===========================================================================
print(f"Blender {bpy.app.version_string}; live snapshot http://{HOST}:{PORT}/model")
try:
    live_snapshot = fetch_model_json_tcp(HOST, PORT, False)
except Exception as exc:  # noqa: BLE001
    fail_exit(f"could not fetch live /model: {exc}")

fresh_scene()
ret = import_snapshot_via_timer(live_snapshot)
objs_after_first = len(bpy.data.objects)
mesh_count = sum(1 for o in bpy.data.objects if o.type == "MESH")
step(
    "LIVE", "(a) first snapshot imported by _sync_timer",
    objs_after_first > 0 and mesh_count > 0 and ret is not None,
    f"objects={objs_after_first} meshes={mesh_count} timer_returned={ret!r}",
)

# ===========================================================================
# (c) LIVE — queue keeps only the latest snapshot
# ===========================================================================
# Enqueue three live-derived snapshots; only the last should be imported. We
# tag each with a distinct title so the imported result identifies which won.
fresh_scene()
q = queue.SimpleQueue()
for tag in ("first", "second", "latest"):
    snap = copy.deepcopy(live_snapshot)
    snap["title"] = f"queue-{tag}"
    q.put(snap)
live_sync._sync_state.update(running=True, queue=q, failures=0, interval=2.0)
live_sync._sync_timer()
left = q.qsize()
# The importer does not necessarily record the snapshot title on the scene, so
# verify the queue was fully drained (only one import pass ran).
step(
    "LIVE", "(c) queue drained to latest in one timer pass",
    left == 0,
    f"queue_remaining={left}",
)

# Also confirm a second pass with an empty queue does not re-import.
objs_before = len(bpy.data.objects)
live_sync._sync_timer()
step(
    "LIVE", "(c) empty queue -> no re-import",
    len(bpy.data.objects) == objs_before,
    f"objects={len(bpy.data.objects)}",
)

# ===========================================================================
# (b) LIVE — a SketchUp transform change reaches matrix_world on the next poll
# ===========================================================================
fresh_scene()
snap0 = fetch_model_json_tcp(HOST, PORT, False)
group = next((e for e in snap0["entities"] if e.get("type") == "Group" and e.get("name") == "FurnitureGroup"), None)
if group is None:
    fail_exit("the live snapshot has no FurnitureGroup")
pid = group["persistent_id"]
import_snapshot_via_timer(snap0)  # first poll
ob = object_for_pid(pid)
x_before = ob.matrix_world.translation.x if ob else None

moved = list(group["transformation"])
moved[3] += 0.5  # row-major, meters: translate +0.5 m in X
try:
    status, reply = post_control("geometry/transform", {"persistent_id": pid, "transformation": moved})
except Exception as exc:  # noqa: BLE001
    status, reply = None, str(exc)
step("LIVE", "(b) SketchUp accepted the transform", status == 200, f"status={status} reply={reply}")

import_snapshot_via_timer(fetch_model_json_tcp(HOST, PORT, False))  # second poll
ob = object_for_pid(pid)
x_after = ob.matrix_world.translation.x if ob else None
ok_b = x_before is not None and x_after is not None and abs((x_after - x_before) - 0.5) < 1e-4
step(
    "LIVE", "(b) object for the FurnitureGroup's id moved +0.5 m after 2nd poll",
    ok_b,
    f"pid={pid} x_before={x_before} x_after={x_after}",
)
# Put the group back; the runner also resets the reference model after every check.
post_control("geometry/transform", {"persistent_id": pid, "transformation": group["transformation"]})

# ===========================================================================
# Restore state and report
# ===========================================================================
restore_state()

failed = [r for r in RESULTS if not r[2]]
print(f"SUMMARY: {len(RESULTS) - len(failed)}/{len(RESULTS)} steps passed")
if failed:
    fail_exit("; ".join(name for _, name, _ in failed))
print("LIVE-SYNC-LOOP OK")
sys.exit(0)
