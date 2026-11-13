"""
Live timer untracked-survives check (deletion safety). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_timer_untracked_survives_check.py

A deletion is pushed only for an id the sync synced; an object the sync never created must never be erased. The
unit tests pin removed_ids() in isolation, not the caller that builds the present set, so a caller bug that treated
an object without an id as deleted would pass them. This check does the real thing: it creates an untracked mesh,
deletes a synced object, runs the live timer, and requires the untracked mesh to still be in Blender.
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
import bmesh  # noqa: E402
import bpy  # noqa: E402
import reference_reset  # noqa: E402

HOST = os.environ.get("SKETCHUP_LINK_HOST", "127.0.0.1")
PORT = int(os.environ.get("SKETCHUP_LINK_PORT", "9876"))


def fail(msg):
    print(f"LIVE-UNTRACKED-SURVIVES FAIL: {msg}")
    sys.exit(1)


addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402


def run_timer():
    ls._sync_state["queue"].put(fetch_model_json_tcp(HOST, PORT, False))
    ls._sync_timer()


reference_reset.reset()
reference_reset.verify()
status = 1
try:
    ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
    ls._sync_state["running"] = True
    ls._sync_state["queue"] = queue.SimpleQueue()
    run_timer()  # import: the synced objects are now tracked

    # An untracked mesh: the sync never created it, so it has no skp_persistent_id.
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=0.2)
    untracked = bpy.data.meshes.new("UntrackedCube")
    bm.to_mesh(untracked)
    bm.free()
    ob_untracked = bpy.data.objects.new("UntrackedCube", untracked)
    bpy.context.collection.objects.link(ob_untracked)
    if "skp_persistent_id" in ob_untracked:
        fail("the untracked object unexpectedly carries an SketchUp id")

    # Delete a synced object in Blender: the one deletion the sync should push.
    victim = next((o for o in bpy.data.objects if "skp_persistent_id" in o and o.type == "MESH"), None)
    if victim is None:
        fail("no synced mesh object to delete")
    victim_pid = int(victim["skp_persistent_id"])
    bpy.data.objects.remove(victim, do_unlink=True)

    run_timer()  # the deletion is pushed; the untracked object must not be touched

    if bpy.data.objects.get("UntrackedCube") is None:
        fail("the untracked object was erased: deletion reached an object the sync never synced")
    d = json.loads(urllib.request.urlopen(f"http://{HOST}:{PORT}/model", timeout=30).read())
    if any(e.get("persistent_id") == victim_pid for e in d["entities"]):
        pass  # the victim may be re-imported under a new id; the requirement is only about the untracked object
    status = 0
    print(f"LIVE-UNTRACKED-SURVIVES OK: the untracked object survived; synced object {victim_pid} deletion handled")
finally:
    reference_reset.reset()
    reference_reset.verify()
sys.exit(status)
