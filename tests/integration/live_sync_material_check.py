"""
Live Blender -> SketchUp material round trip (milestone 1). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_sync_material_check.py

Imports the live snapshot, changes the colour of a tagged chair's material in Blender,
pushes the captured edit through /control/material using SketchUp's real current colour
for the conflict decision, verifies SketchUp changed, and restores the factory colour.
Objects are found by stored SketchUp id, never by name.
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
MATERIAL = "Blue"
# The reference model's Blue (sketchup_link/server.rb create_test_model_from_factories).
# The baseline must match it: a stale FACTORY made SketchUp look changed by someone else, so
# the conflict rule rightly dropped the edit.
FACTORY = (20, 20, 200)
CHANGED = (200, 50, 50)


def fail(msg):
    print(f"LIVE-MATERIAL FAIL: {msg}")
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


def read_sketchup_color(name):
    for m in get_model().get("materials", []):
        if m.get("name") == name:
            c = m["color"]
            return (c["r"], c["g"], c["b"])
    return None


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

chair = next((o for o in bpy.data.objects if o.get("skp_persistent_id") and o.name.startswith("C-")), None)
if chair is None or chair.data is None:
    fail("could not find the imported chair by its SketchUp id")
chair_pid = int(chair["skp_persistent_id"])

# Give the chair a material whose colour we control, then take it as the synced baseline.
mat = bpy.data.materials.new(MATERIAL)
mat.diffuse_color = (FACTORY[0] / 255, FACTORY[1] / 255, FACTORY[2] / 255, 1.0)
chair.data.materials.clear()
chair.data.materials.append(mat)
ec.record_import_state()
ec.on_depsgraph_update(bpy.context.scene)
if ec.pending_edits():
    fail("baseline produced pending edits (echo)")

# 1. Change the colour in Blender and capture it.
mat.diffuse_color = (CHANGED[0] / 255, CHANGED[1] / 255, CHANGED[2] / 255, 1.0)
ec.on_depsgraph_update(bpy.context.scene)
edits = ec.drain_pending()
if not any(e.persistent_id == chair_pid and "material" in e.fields for e in edits):
    fail(f"colour change not captured as a material edit: {[(e.persistent_id, e.fields) for e in edits]}")

# 2. Push it. SketchUp's current colour is read live for the conflict decision.
def read_current(pid):
    return SketchUpState(transform=None, color=read_sketchup_color(MATERIAL))

for e in edits:
    base = ec.tracker()._synced[e.persistent_id]
    r = push(e, base,
             read_current=read_current,
             send_transform=lambda p, t: 200,
             send_material=lambda n, c: post("/control/material", {"name": n, "color": {"r": c[0], "g": c[1], "b": c[2]}}),
             material_name_for=lambda p: MATERIAL)
    if r.error:
        fail(f"material push failed: {r.error}")
    if "material" not in r.pushed:
        fail(f"material edit was not pushed (overwritten={r.overwritten})")

# 3. Verify SketchUp now has the Blender colour.
got = read_sketchup_color(MATERIAL)
if got != CHANGED:
    fail(f"SketchUp {MATERIAL} is {got}, expected {CHANGED}")

# 4. Restore the factory colour in SketchUp so the model returns to its reference state.
if post("/control/material", {"name": MATERIAL, "color": {"r": FACTORY[0], "g": FACTORY[1], "b": FACTORY[2]}}) != 200:
    fail("could not restore the factory material colour")

print("LIVE-MATERIAL OK: colour round trip (edit captured, pushed, verified, restored)")
sys.exit(0)
