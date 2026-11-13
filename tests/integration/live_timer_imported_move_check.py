"""
Live timer imported-move check (functionality gap: moving an imported object was never pushed). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_timer_imported_move_check.py

An imported object (a SketchUp group the importer built) must have its transform tracked from the moment it is
imported, so a later move in Blender reaches SketchUp through the real timer. Before the fix the live import never
recorded the imported baseline (record_import_state was only ever called by the integration checks themselves),
so the move was invisible: the object was untracked and the transform never pushed. This check uses no test-only
setup: import, move the group, run the live timer, and require SketchUp's group to have moved.
The reference model is restored before and after.
"""
import json
import os
import queue
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
for p in (REPO, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import addon_utils  # noqa: E402
import bpy  # noqa: E402
import reference_reset  # noqa: E402

HOST = os.environ.get("SKETCHUP_LINK_HOST", "127.0.0.1")
PORT = int(os.environ.get("SKETCHUP_LINK_PORT", "9876"))
BASE = f"http://{HOST}:{PORT}"
SHIFT = 0.5  # metres


def fail(msg):
    print(f"LIVE-IMPORTED-MOVE FAIL: {msg}")
    sys.exit(1)


addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402


def run_timer():
    ls._sync_state["queue"].put(fetch_model_json_tcp(HOST, PORT, False))
    ls._sync_timer()


def model():
    return json.loads(urllib.request.urlopen(BASE + "/model", timeout=30).read())


reference_reset.reset()
reference_reset.verify()
status = 1
try:
    ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
    ls._sync_state["running"] = True
    ls._sync_state["queue"] = queue.SimpleQueue()
    run_timer()  # import: the imported groups now exist in Blender

    group = next((o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("G-VisualCube")), None)
    if group is None or "skp_persistent_id" not in group:
        fail("no imported G-VisualCube object with a SketchUp id to move")
    pid = int(group["skp_persistent_id"])
    before_x = next(e["transformation"][3] for e in model()["entities"] if e.get("persistent_id") == pid)

    # The import rebuilt the objects, so the group found above is stale: move the object that is live now.
    group = next(o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("G-VisualCube"))
    group.location.x += SHIFT  # a real move in Blender, with no test-only bookkeeping
    # Blender evaluates the depsgraph (which queues the edit) on a view-layer update, as it does between frames.
    bpy.context.view_layer.update()
    run_timer()  # the live timer must detect and push it

    after_x = next(e["transformation"][3] for e in model()["entities"] if e.get("persistent_id") == pid)
    if abs((after_x - before_x) - SHIFT) > 1e-3:
        fail(f"SketchUp group {pid} did not move: x {before_x} -> {after_x} (expected +{SHIFT} m)")

    status = 0
    print(f"LIVE-IMPORTED-MOVE OK: imported group {pid} moved in Blender and the move reached SketchUp "
          f"(x {before_x:.3f} -> {after_x:.3f})")
finally:
    reference_reset.reset()
    reference_reset.verify()
sys.exit(status)
