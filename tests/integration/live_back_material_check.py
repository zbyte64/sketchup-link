"""
Live back-material check (functionality gap: faces painted only on their back). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_back_material_check.py

A Blender polygon carries one material, a SketchUp face two. The reference model has a top-level face whose
front is unpainted and whose back is Blue; viewed in SketchUp it shows Blue, and it must not import as the
default grey. Contract: every polygon attributed to a face takes the face's front material if it has one,
otherwise its back material. Polygons are matched to faces through the skp_face_id attribute layer.
"""
import os
import queue
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import addon_utils  # noqa: E402
import bpy  # noqa: E402

HOST = os.environ.get("SKETCHUP_LINK_HOST", "127.0.0.1")
PORT = int(os.environ.get("SKETCHUP_LINK_PORT", "9876"))


def fail(msg):
    print(f"LIVE-BACK-MATERIAL FAIL: {msg}")
    sys.exit(1)


addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402

snap = fetch_model_json_tcp(HOST, PORT, False)
ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
ls._sync_state["running"] = True
ls._sync_state["queue"] = queue.SimpleQueue()
ls._sync_state["queue"].put(snap)
ls._sync_timer()

# Expected material per top-level face: front if painted, else back.
expected = {}
for e in snap["entities"]:
    if e.get("type") == "Face" and (e.get("material") or e.get("back_material")):
        expected[e["persistent_id"]] = e.get("material") or e.get("back_material")
back_only = [pid for pid, _ in expected.items()
             if not next(e for e in snap["entities"] if e.get("persistent_id") == pid).get("material")]
if not back_only:
    fail("the reference has no top-level face painted only on its back; the check would prove nothing")

seen = {}
for ob in bpy.data.objects:
    if ob.type != "MESH" or ob.data.attributes.get("skp_face_id") is None:
        continue
    layer = ob.data.attributes["skp_face_id"]
    for poly in ob.data.polygons:
        pid = int(layer.data[poly.index].value)
        if pid in expected:
            mat = ob.data.materials[poly.material_index] if ob.data.materials else None
            seen.setdefault(pid, set()).add(mat.name if mat else None)

for pid, want in expected.items():
    got = seen.get(pid)
    if not got:
        fail(f"face {pid} has no attributed polygon in Blender")
    if got != {want}:
        fail(f"face {pid} should import as {want!r}, its polygons use {sorted(map(str, got))}")

print(f"LIVE-BACK-MATERIAL OK: {len(expected)} painted face(s), {len(back_only)} back-only, materials match")
sys.exit(0)
