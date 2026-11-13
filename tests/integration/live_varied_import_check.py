"""
Live varied-model import check (gap 11). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_varied_import_check.py

The complex-model check covers nesting, a texture slot and a dense grid. This one covers what it does not: many
component instances of one definition, several layers, and a textured material. It asserts that:
  - every instance of the shared definition is present in the snapshot and is an identified Blender object, once;
  - instance identities are unique (no two instances collapse to one object);
  - the instances span the expected layers;
  - the textured material exists in Blender;
  - every SketchUp face in the snapshot is named by a Blender polygon (none missing, none extra).
The scene is built in SketchUp through the MCP tunnel and removed afterwards; the reference model is restored
with the shared reset before and after.
"""
import collections
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
N_INSTANCES = 30
LAYERS = ["LayerA", "LayerB", "LayerC"]


def fail(msg):
    print(f"LIVE-VARIED FAIL: {msg}")
    sys.exit(1)


BUILD = f'''
m = Sketchup.active_model
root = m.entities.add_group
root.name = "VariedScene"
defn = m.definitions.add("VariedPart")
defn.entities.add_face([[0,0,0],[0.1,0,0],[0.1,0.1,0],[0,0.1,0]])
layers = {LAYERS!r}.map {{ |n| m.layers.add(n) }}
({0}...{N_INSTANCES}).each do |i|
  inst = root.entities.add_instance(defn, Geom::Transformation.new([i * 0.2, 1.0, 0]))
  inst.layer = layers[i % 3]
end
mat = m.materials.add("TexturedWall")
root.entities.add_face([[0,2,0],[1,2,0],[1,3,0],[0,3,0]]).material = mat
"ok"
'''.replace("{0}", "0")

addon_utils.enable("blender_plugin", default_set=True, persistent=False)

reference_reset.reset()
status = 1
try:
    reply = reference_reset.mcp_eval(BUILD)
    if '"ok"' not in reply:
        fail(f"could not build the varied model in SketchUp: {reply[-160:]}")
    ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
    ls._sync_state["running"] = True
    ls._sync_state["queue"] = queue.SimpleQueue()
    snap = fetch_model_json_tcp(HOST, PORT, False)
    ls._sync_state["queue"].put(snap)
    ls._sync_timer()

    root = next((e for e in snap["entities"] if e.get("name") == "VariedScene"), None)
    if root is None:
        fail("the snapshot has no VariedScene group")
    insts = [e for e in root.get("entities", []) if e.get("type") == "ComponentInstance"]
    if len(insts) != N_INSTANCES:
        fail(f"the snapshot has {len(insts)} instances, expected {N_INSTANCES}")
    inst_ids = [int(e["persistent_id"]) for e in insts]

    identified = collections.Counter(int(o["skp_persistent_id"]) for o in bpy.data.objects
                                     if "skp_persistent_id" in o and o.get("skp_link_import"))
    # Spec (geometry_fidelity.feature): entities on hidden layers are excluded. An instance on a hidden layer must
    # be absent from Blender; one on a visible layer must be identified. Hidden-ness comes from the snapshot's own
    # layer flags, not a hard-coded layer name.
    hidden_layers = {l["name"] for l in snap.get("layers", []) if not l.get("visible", True)}
    should_import = [e for e in insts if e.get("layer") not in hidden_layers]
    should_skip = [e for e in insts if e.get("layer") in hidden_layers]
    missing = [int(e["persistent_id"]) for e in should_import if identified[int(e["persistent_id"])] == 0]
    if missing:
        fail(f"{len(missing)} visible-layer instance(s) are not identified Blender objects")
    leaked = [int(e["persistent_id"]) for e in should_skip if identified[int(e["persistent_id"])] > 0]
    if leaked:
        fail(f"{len(leaked)} instance(s) on hidden layers were imported; the spec excludes them")
    inst_ids = [int(e["persistent_id"]) for e in should_import]
    collapsed = [pid for pid in inst_ids if identified[pid] > 1]
    if collapsed:
        fail(f"{len(collapsed)} instance id(s) map to more than one Blender object")

    layers_seen = {e.get("layer") for e in should_import}
    visible_expected = set(LAYERS) - hidden_layers
    if layers_seen != visible_expected:
        fail(f"visible-layer instances span {sorted(layers_seen)}, expected {sorted(visible_expected)}")

    if bpy.data.materials.get("TexturedWall") is None:
        fail("the textured material TexturedWall was not imported")

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
    for o in bpy.data.objects:
        if o.type == "MESH" and o.data.attributes.get("skp_face_id"):
            layer = o.data.attributes["skp_face_id"]
            attributed |= {int(layer.data[i].value) for i in range(len(o.data.polygons))}
    attributed.discard(0)
    if sketchup_faces - attributed:
        fail(f"{len(sketchup_faces - attributed)} SketchUp face(s) have no Blender polygon")
    if attributed - sketchup_faces:
        fail(f"{len(attributed - sketchup_faces)} Blender polygon(s) name a face that is not in SketchUp")

    status = 0
    print(f"LIVE-VARIED OK: {len(should_import)} visible-layer instances identified once each, "
          f"{len(should_skip)} hidden-layer instances excluded, textured material present, {len(sketchup_faces)} faces attributed")
finally:
    try:
        reference_reset.mcp_eval('Sketchup.active_model.entities.grep(Sketchup::Group).each { |g| g.erase! if g.name == "VariedScene" }; "ok"')
    except Exception:
        pass
    reference_reset.reset()
sys.exit(status)
