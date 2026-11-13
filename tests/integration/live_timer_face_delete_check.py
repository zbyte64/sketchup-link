"""
Live timer face-delete check (functionality gap: deleting a face inside an imported object). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_timer_face_delete_check.py

Deleting whole objects already round-trips (live_timer_delete_check). Deleting some faces of an imported object
did not: the import rebuilt them. Deletes, in Blender, the polygons of one face of VisualCube (a group) and of the
Red loose top-level face, runs the real timer, and asserts that SketchUp erased exactly those two faces: both ids
are gone, VisualCube has one face fewer, every other face keeps its id, and after the next import Blender has no
polygon attributed to either deleted face. The reference model is restored before and after.
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
    print(f"LIVE-TIMER-FACE-DELETE FAIL: {msg}")
    sys.exit(1)


def snapshot():
    return json.loads(urllib.request.urlopen(f"http://{HOST}:{PORT}/model", timeout=30).read())


def all_faces(d):
    """persistent id -> owner name ('' for top level) for every face at the top level and in groups."""
    out = {}
    for e in d["entities"]:
        if e.get("type") == "Face":
            out[e["persistent_id"]] = ""
        elif e.get("type") == "Group":
            for f in e.get("entities", []):
                if f.get("type") == "Face":
                    out[f["persistent_id"]] = e.get("name") or "group"
    return out


def delete_face_polygons(ob, face_pid):
    layer = ob.data.attributes["skp_face_id"]
    doomed = {p.index for p in ob.data.polygons if int(layer.data[p.index].value) == face_pid}
    if not doomed:
        fail(f"no polygon of {ob.name} names face {face_pid}")
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in doomed], context="FACES_ONLY")
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()


addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402


def run_timer():
    _snap = fetch_model_json_tcp(HOST, PORT, False)
    _snap["two_way_enabled"] = True  # this check exercises two-way editing
    ls._sync_state["queue"].put(_snap)
    ls._sync_timer()


reference_reset.reset()
reference_reset.verify()
status = 1
try:
    ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
    ls._sync_state["running"] = True
    ls._sync_state["queue"] = queue.SimpleQueue()
    run_timer()  # import and record the baseline

    d0 = snapshot()
    before = all_faces(d0)
    cube = next(e for e in d0["entities"] if e.get("type") == "Group" and e.get("name") == "VisualCube")
    cube_faces = [f["persistent_id"] for f in cube["entities"] if f.get("type") == "Face"]
    red = next((e["persistent_id"] for e in d0["entities"] if e.get("type") == "Face" and e.get("material") == "Red"),
               None)
    if red is None or len(cube_faces) < 2:
        fail("the reference model lacks the Red loose face or VisualCube's faces")
    cube_target = cube_faces[0]

    cube_ob = next((o for o in bpy.data.objects if o.get("skp_persistent_id") == cube["persistent_id"]), None)
    loose_ob = next((o for o in bpy.data.objects if o.name.startswith("_(Loose Entity)")), None)
    if cube_ob is None or loose_ob is None:
        fail("VisualCube or the loose-geometry object is missing in Blender")
    delete_face_polygons(cube_ob, cube_target)
    delete_face_polygons(loose_ob, red)

    run_timer()  # pushes the deletes (the snapshot it imports was fetched before the push)
    run_timer()  # the next poll: imports SketchUp's state after the deletes

    after = all_faces(snapshot())
    gone = set(before) - set(after)
    if gone != {cube_target, red}:
        fail(f"expected exactly faces {sorted({cube_target, red})} erased, SketchUp erased {sorted(gone)}"
             f" and added {sorted(set(after) - set(before))}")
    if set(after) - set(before):
        fail(f"new faces appeared: {sorted(set(after) - set(before))}")
    n_cube = sum(1 for owner in after.values() if owner == "VisualCube")
    if n_cube != len(cube_faces) - 1:
        fail(f"VisualCube has {n_cube} faces, expected {len(cube_faces) - 1}")

    for ob in bpy.data.objects:
        layer = ob.data.attributes.get("skp_face_id") if ob.type == "MESH" else None
        if layer is not None and {int(v.value) for v in layer.data} & {cube_target, red}:
            fail(f"{ob.name} still has polygons attributed to a deleted face after the re-import")

    status = 0
    print(f"LIVE-TIMER-FACE-DELETE OK: grouped face {cube_target} and loose face {red} erased in SketchUp, "
          f"{len(after)} other faces kept their ids")
finally:
    reference_reset.reset()
    reference_reset.verify()
sys.exit(status)
