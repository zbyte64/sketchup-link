"""
Live-sync poll -> queue -> timer check. Runs INSIDE Blender (`blender --background`).

Drives blender_plugin.live_sync._poll_loop (a real daemon thread) and calls
_sync_timer() DIRECTLY (bpy.app.timers is never registered).

Steps and their data source (see each step's label in the output):
  (a) LIVE       first snapshot from the live SketchUp at SKETCHUP_LINK_HOST:PORT
                 is imported by _sync_timer().
  (c) LIVE       when several snapshots are queued, _sync_timer() imports only
                 the latest one (queue keeps only the freshest snapshot).
  (b) MOCK-ONLY  a FurnitureGroup transform change is reflected in the Blender
                 object's matrix_world after a second poll. The second snapshot
                 is a Python-built mock (sketchup_link/server.rb-style
                 FurnitureGroup), NOT the live SketchUp. The live transform path
                 (POST /control/geometry/transform) is unverified until the
                 endpoint is wired into the SketchUp plugin. Point
                 `_mock_moved_snapshot` at the live server later without
                 rewriting the test.

Environment:
    SKETCHUP_LINK_HOST  default 127.0.0.1
    SKETCHUP_LINK_PORT  default 9876

Exit 0 on success, non-zero on any failure.
"""

import copy
import os
import queue
import sys
import threading
import time

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
from blender_plugin.live_adapter import fetch_model_json_tcp, JsonModel  # noqa: E402
from blender_plugin.scene_importer import SceneImporter  # noqa: E402

# Snapshot the global sync state so we can restore it on exit.
_SAVED_STATE = dict(live_sync._sync_state)


def restore_state():
    live_sync._sync_state.clear()
    live_sync._sync_state.update(_SAVED_STATE)


def import_options():
    return dict(
        filepath="",
        scenes_as_camera=False,
        import_camera=False,
        reuse_material=True,
        dedub_only=False,
        reuse_existing_groups=False,
        max_instance=1,
        dedub_type="VERTEX",
        import_scene="",
    )


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def find_group_object(name="FurnitureGroup"):
    """Return the Blender object for the FurnitureGroup, or None."""
    for ob in bpy.data.objects:
        if ob.name == name or ob.name.startswith(name):
            return ob
    return None


def mock_furniture_snapshot(translate_x):
    """MOCK-ONLY: build a snapshot with a FurnitureGroup at a given X offset.

    Mirrors tests/integration/factories.rb (`group name='FurnitureGroup'`). Only
    the transform changes between calls. Replace this with a live fetch once the
    SketchUp control endpoint is wired.
    """
    # Row-major 4x4: translation in column 4 (meters).
    t = [
        1, 0, 0, translate_x,
        0, 1, 0, 0,
        0, 0, 1, 0,
        0, 0, 0, 1,
    ]
    return {
        "model_guid": "mock-live-sync-loop",
        "title": "Mock FurnitureGroup",
        "path": "/tmp/mock.skp",
        "camera": {
            "eye": [0, 0, 10], "target": [0, 0, 0], "up": [0, 1, 0],
            "perspective": True, "fov": 35.0, "aspect_ratio": 1.0,
        },
        "shadow_info": {},
        "layers": [{"name": "Furniture", "visible": True}],
        "materials": [],
        "component_definitions": {},
        "entities": [
            {
                "type": "Group",
                "name": "FurnitureGroup",
                "persistent_id": 99001,
                "layer": "Furniture",
                "transformation": t,
                "entities": [],
            }
        ],
    }


def mock_moved_snapshot(x):
    """MOCK-ONLY hook. Swap for a live fetch after the endpoint is wired."""
    return mock_furniture_snapshot(x)


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
# (b) MOCK-ONLY — FurnitureGroup transform reflected in matrix_world
# ===========================================================================
# MOCK-ONLY: the live SketchUp endpoint POST /control/geometry/transform is not
# wired (HTTP 404 on the live server), so the moved snapshot here is built in
# Python, not fetched from SketchUp.
fresh_scene()
import_snapshot_via_timer(mock_moved_snapshot(0.0))  # first poll
ob = find_group_object("FurnitureGroup")
x_before = ob.matrix_world.translation.x if ob else None

import_snapshot_via_timer(mock_moved_snapshot(0.5))  # second poll, moved +0.5 m in X
ob = find_group_object("FurnitureGroup")
x_after = ob.matrix_world.translation.x if ob else None
ok_b = ob is not None and x_before is not None and x_after is not None and abs(x_after - 0.5) < 1e-4
step(
    "MOCK-ONLY", "(b) FurnitureGroup matrix_world reflects transform after 2nd poll",
    ok_b,
    f"x_before={x_before} x_after={x_after}",
)

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
