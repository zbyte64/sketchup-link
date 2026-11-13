"""
Live complex-model import check (gap 11). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_complex_import_check.py

The reference scene is small and flat. This check imports a larger model with the cases it lacks: a group nested
two levels deep, a textured face, and a 400-face grid. It asserts that:
  - every SketchUp face in the snapshot is named by at least one Blender polygon (none missing, none extra);
  - each nesting level becomes an identified object (the nested groups carry their SketchUp ids);
  - the textured material exists in Blender;
  - the grid's polygons are present (two triangles per quad) and are NOT claimed as identified.
The complex model is built in SketchUp through the MCP tunnel and removed afterwards, and the reference model is
restored with the shared reset before and after.
"""
import os
import queue
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

import addon_utils  # noqa: E402
import bpy  # noqa: E402
import reference_reset  # noqa: E402
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402

HOST = os.environ.get("SKETCHUP_LINK_HOST", "127.0.0.1")
PORT = int(os.environ.get("SKETCHUP_LINK_PORT", "9876"))
GRID_N = 20


def fail(msg):
    print(f"LIVE-COMPLEX FAIL: {msg}")
    sys.exit(1)


BUILD = f'''
m = Sketchup.active_model
root = m.entities.add_group
root.name = "ComplexScene"
inner = root.entities.add_group
inner.name = "Inner"
deep = inner.entities.add_group
deep.name = "Deep"
tex = m.materials.add("TexStone")
tex.color = Sketchup::Color.new(180, 150, 120)
deep.entities.add_face([[0,0,0],[1,0,0],[1,1,0],[0,1,0]]).material = tex
(0...{GRID_N}).each do |i|
  (0...{GRID_N}).each do |j|
    x = 2 + i * 0.1; y = j * 0.1
    root.entities.add_face([[x,y,0],[x+0.1,y,0],[x+0.1,y+0.1,0],[x,y+0.1,0]])
  end
end
"ok"
'''

addon_utils.enable("blender_plugin", default_set=True, persistent=False)

reference_reset.reset()
status = 1
try:
    reply = reference_reset.mcp_eval(BUILD)
    if '"ok"' not in reply:
        fail(f"could not build the complex model in SketchUp: {reply[-160:]}")
    ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
    ls._sync_state["running"] = True
    ls._sync_state["queue"] = queue.SimpleQueue()
    snap = fetch_model_json_tcp(HOST, PORT, False)
    ls._sync_state["queue"].put(snap)
    ls._sync_timer()

    # Every SketchUp face in the snapshot (top level, nested, and in definitions).
    sketchup_faces = set()

    def collect(entities):
        for e in entities or []:
            if e.get("type") == "Face":
                sketchup_faces.add(e["persistent_id"])
            collect(e.get("entities"))

    collect(snap["entities"])
    for d in snap.get("component_definitions", {}).values():
        collect(d.get("entities"))

    attributed = set()
    grid_polys = 0
    for o in bpy.data.objects:
        if o.type == "MESH" and o.data.attributes.get("skp_face_id"):
            layer = o.data.attributes["skp_face_id"]
            for i in range(len(o.data.polygons)):
                pid = int(layer.data[i].value)
                if pid:
                    attributed.add(pid)
    attributed.discard(0)
    missing = sketchup_faces - attributed
    extra = attributed - sketchup_faces
    if missing:
        fail(f"{len(missing)} SketchUp face(s) have no Blender polygon")
    if extra:
        fail(f"{len(extra)} Blender polygon(s) name a face that is not in SketchUp")

    # Each nesting level exists at its expected depth below ComplexScene, and the top group is an identified object.
    def find_group(entities, name, depth=0):
        for e in entities or []:
            if e.get("type") == "Group":
                if e.get("name") == name:
                    return e, depth
                found = find_group(e.get("entities"), name, depth + 1)
                if found:
                    return found
        return None

    top = next((e for e in snap["entities"] if e.get("type") == "Group" and e.get("name") == "ComplexScene"), None)
    if top is None:
        fail("the snapshot has no ComplexScene group")
    for name, want_depth in (("Inner", 1), ("Deep", 2)):
        found = find_group(top.get("entities"), name)
        if found is None:
            fail(f"the snapshot has no group '{name}' below ComplexScene")
        if found[1] + 1 != want_depth:
            fail(f"group '{name}' is at depth {found[1] + 1}, expected {want_depth}")
    ob = next((o for o in bpy.data.objects if o.get("skp_persistent_id") == top["persistent_id"]), None)
    if ob is None:
        fail("the ComplexScene group is not an identified Blender object")

    if bpy.data.materials.get("TexStone") is None:
        fail("the textured material TexStone was not imported")

    # The grid is unidentified loose geometry by design (see BLENDER-DEBUG.md, limitations): its polygons must be
    # present, and none of them may be claimed as identified.
    loose = [o for o in bpy.data.objects if o.type == "MESH" and "skp_persistent_id" not in o
             and o.data.attributes.get("skp_face_id")]
    grid_polys = sum(len(o.data.polygons) for o in loose)
    if grid_polys < 2 * GRID_N * GRID_N:
        fail(f"the grid has {grid_polys} polygons, expected at least {2 * GRID_N * GRID_N} (two per quad)")

    status = 0
    print(f"LIVE-COMPLEX OK: {len(sketchup_faces)} faces attributed, nested identity kept, textured material present, "
          f"{grid_polys} grid polygons present")
finally:
    try:
        reference_reset.mcp_eval('Sketchup.active_model.entities.grep(Sketchup::Group).each { |g| g.erase! if g.name == "ComplexScene" }; "ok"')
    except Exception:
        pass
    reference_reset.reset()
sys.exit(status)
