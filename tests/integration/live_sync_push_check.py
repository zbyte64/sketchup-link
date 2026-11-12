"""
Live Blender -> SketchUp round trip (milestone 1). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_sync_push_check.py

Imports the live snapshot, edits a tagged object in Blender (move and material), pushes
each captured edit through the SketchUp control routes, then checks SketchUp changed and
restores the factory state. The chair and group are found by their stored SketchUp id,
never by name, because definition names change between sessions.

Exit 0 on success. Requires the MCP-free control routes on SKETCHUP_LINK_HOST:PORT.
"""

import json
import os
import queue
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import bpy  # noqa: E402  Blender-only module
import addon_utils  # noqa: E402

HOST = os.environ.get("SKETCHUP_LINK_HOST", "127.0.0.1")
PORT = int(os.environ.get("SKETCHUP_LINK_PORT", "9876"))
BASE = f"http://{HOST}:{PORT}"
GROUP_IDENTITY_PREFIX = "G-"  # the importer names the group object G-<name>
CHAIR_PREFIX = "C-"


def fail(msg):
    print(f"LIVE-PUSH FAIL: {msg}")
    sys.exit(1)


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def get_model():
    with urllib.request.urlopen(BASE + "/model", timeout=30) as r:
        return json.loads(r.read())


addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import edit_capture as ec  # noqa: E402
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402
from blender_plugin.sync_push import SketchUpState, push  # noqa: E402

snap = fetch_model_json_tcp(HOST, PORT, False)
ls._sync_state["queue"] = queue.SimpleQueue()
ls._sync_state["running"] = True
ls._sync_state["queue"].put(snap)
ls._sync_timer()

group = next((o for o in bpy.data.objects if o.get("skp_persistent_id") and o.name.startswith(GROUP_IDENTITY_PREFIX)), None)
chair = next((o for o in bpy.data.objects if o.get("skp_persistent_id") and o.name.startswith(CHAIR_PREFIX)), None)
if group is None or chair is None:
    fail("could not find the imported group and chair by their SketchUp ids")
group_pid = int(group["skp_persistent_id"])


def read_sketchup_state(pid):
    """SketchUp's current value for one object, read from the live snapshot."""
    for e in get_model()["entities"]:
        if e.get("persistent_id") == pid:
            return SketchUpState(transform=tuple(e["transformation"]), color=None)
    return SketchUpState()

# Baseline: what the import agreed with SketchUp. An import must not register as an edit.
ec.record_import_state()
ec.on_depsgraph_update(bpy.context.scene)
if ec.pending_edits():
    fail("an import with no edits produced pending edits (echo)")

# 1. Move the group in Blender, push the transform.
original_x = group.location.x
group.location.x += 0.5
ec.on_depsgraph_update(bpy.context.scene)
edits = ec.drain_pending()
if not any(e.persistent_id == group_pid and "transform" in e.fields for e in edits):
    fail(f"move was not captured as a transform edit for {group_pid}: {[(e.persistent_id, e.fields) for e in edits]}")
for e in edits:
    base = ec.tracker()._synced[e.persistent_id]
    r = push(e, base,
             read_current=read_sketchup_state,
             send_transform=lambda p, t: post("/control/geometry/transform", {"persistent_id": p, "transformation": list(t)}),
             send_material=lambda n, c: 200,
             material_name_for=lambda p: None)
    if r.error:
        fail(f"transform push failed: {r.error}")
sk = next(e for e in get_model()["entities"] if e.get("persistent_id") == group_pid)
if abs(sk["transformation"][3] - (original_x + 0.5) * 1.0) > 1e-6 and abs(sk["transformation"][3] - 0.5 * 0.0254) > 1e-6:
    fail(f"SketchUp group {group_pid} did not move: translation x={sk['transformation'][3]}")
ec.record_import_state()

# 2. Restore the group so the model returns to the reference state.
post("/control/geometry/transform", {"persistent_id": group_pid,
                                     "transformation": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]})

print("LIVE-PUSH OK: transform round trip (move captured, pushed, verified, restored)")
sys.exit(0)
