"""
Live import attribution check (gap 5, two-way mesh edits). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_import_attribution_check.py

A reshape can only be pushed for an edited polygon if that polygon names the SketchUp face it came from.
The importer triangulates faces and merges vertices, so a Blender polygon does not correspond to a
SketchUp face by index: FurnitureGroup has one SketchUp face but two Blender polygons. This check defines
the attribution the importer must provide: every SketchUp face of a group is named by at least one
polygon of that group's mesh, and every polygon names exactly one SketchUp face (no orphans).
Objects are found by stored SketchUp id.
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
    print(f"LIVE-ATTRIBUTION FAIL: {msg}")
    sys.exit(1)


try:
    pass
except Exception:
    pass
addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402

snap = fetch_model_json_tcp(HOST, PORT, False)
ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
ls._sync_state["running"] = True
ls._sync_state["queue"] = queue.SimpleQueue()
ls._sync_state["queue"].put(snap)
ls._sync_timer()

group_json = next((e for e in snap["entities"] if e.get("type") == "Group" and e.get("name") == "FurnitureGroup"), None)
if group_json is None:
    fail("the snapshot has no FurnitureGroup")
sketchup_faces = {f["persistent_id"] for f in group_json["entities"] if f.get("type") == "Face"}

ob = next((o for o in bpy.data.objects if o.get("skp_persistent_id") == group_json["persistent_id"]), None)
if ob is None:
    fail("no Blender object is identified with the FurnitureGroup's SketchUp id")

# Polygons cannot hold custom properties, so the attribution lives in a per-face integer attribute
# layer named skp_face_id on the mesh. Its absence is a failure, not a set of orphans.
layer = ob.data.attributes.get("skp_face_id")
if layer is None:
    fail("the imported mesh has no skp_face_id attribute layer: polygons do not name their SketchUp faces")

attributed = {}
for poly in ob.data.polygons:
    value = int(layer.data[poly.index].value)
    attributed.setdefault(value if value != 0 else None, []).append(poly.index)

if None in attributed:
    fail(f"{len(attributed[None])} polygon(s) do not name a SketchUp face (orphans)")
named = set(attributed.keys())
missing = sketchup_faces - named
if missing:
    fail(f"SketchUp faces with no polygon in the mesh: {sorted(missing)}")
extra = named - sketchup_faces
if extra:
    fail(f"polygons name faces that are not in the group: {sorted(extra)}")

print(f"LIVE-ATTRIBUTION OK: {len(sketchup_faces)} SketchUp face(s), {len(list(ob.data.polygons))} polygon(s), attributed")
print("ATTRIBUTION-DONE", flush=True)
sys.exit(0)
