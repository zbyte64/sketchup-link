"""
Live timer stale-snapshot check. Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_timer_stale_snapshot_check.py

The poll thread fetches snapshots on its own schedule, so the snapshot a timer pass imports can predate the
edit that same pass pushes. Importing it rebuilt the old geometry, so the user's edit vanished from Blender
until the next poll. Contract: a snapshot whose fetch started before the last push is not imported; the next
fresh one is. Snapshots are stamped exactly as _poll_loop stamps them (_fetched_at, monotonic time).

Deletes the Red loose face in Blender while a pre-edit snapshot is queued, runs one timer pass, and requires
that the delete reached SketchUp and that Blender still shows it deleted; then a fresh snapshot is imported.
The reference model is restored before and after.
"""
import json
import os
import queue
import sys
import time
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
    print(f"LIVE-TIMER-STALE FAIL: {msg}")
    sys.exit(1)


addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402


def poll():
    """One snapshot, stamped the way _poll_loop stamps it."""
    t = time.monotonic()
    snap = fetch_model_json_tcp(HOST, PORT, False)
    snap["_fetched_at"] = t
    return snap


def red_polygons():
    ob = next((o for o in bpy.data.objects if o.name.startswith("_(Loose Entity)")), None)
    if ob is None:
        return None, []
    layer = ob.data.attributes["skp_face_id"]
    return ob, [p.index for p in ob.data.polygons if int(layer.data[p.index].value) == RED]


# The factory Cube is an untagged mesh: the timer would push it as new geometry, and that push would make the
# first snapshot stale too. Remove the factory objects so the first pass is a plain import.
for _name in ("Cube", "Camera", "Light"):
    if bpy.data.objects.get(_name):
        bpy.data.objects.remove(bpy.data.objects[_name], do_unlink=True)

reference_reset.reset()
reference_reset.verify()
status = 1
try:
    ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
    ls._sync_state["running"] = True
    ls._sync_state["queue"] = queue.SimpleQueue()
    ls._sync_state["queue"].put(poll())
    ls._sync_timer()  # import and record the baseline

    snap0 = fetch_model_json_tcp(HOST, PORT, False)
    RED = next(e["persistent_id"] for e in snap0["entities"] if e.get("type") == "Face" and e.get("material") == "Red")
    stale = poll()  # the poll thread fetched this before the user's edit

    ob, polys = red_polygons()
    if not polys:
        fail("the Red loose face has no polygons after the import")
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in polys], context="FACES_ONLY")
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()

    ls._sync_state["queue"].put(stale)
    ls._sync_timer()  # pushes the delete; must not import the stale snapshot

    in_sketchup = any(e.get("persistent_id") == RED for e in fetch_model_json_tcp(HOST, PORT, False)["entities"])
    if in_sketchup:
        fail("the delete did not reach SketchUp")
    _, polys = red_polygons()
    if polys:
        fail(f"a snapshot fetched before the push was imported: the deleted face is back in Blender "
             f"({len(polys)} polygon(s))")

    ls._sync_state["queue"].put(poll())
    ls._sync_timer()  # the next fresh poll is imported
    ob, polys = red_polygons()
    if ob is None:
        fail("the fresh snapshot after the push was not imported (no loose-geometry object)")
    if polys:
        fail("the fresh snapshot brought the deleted face back")

    status = 0
    print("LIVE-TIMER-STALE OK: a pre-push snapshot was skipped, the edit stayed in Blender, the next poll imported")
finally:
    reference_reset.reset()
    reference_reset.verify()
sys.exit(status)
