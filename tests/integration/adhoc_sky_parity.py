"""Ad-hoc: report sky_type applied by the importer. Run inside Blender with --python."""
import os, sys
REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, REPO)
import bpy
from blender_plugin.live_adapter import fetch_model_json_tcp, JsonModel
from blender_plugin.scene_importer import SceneImporter, _nishita_sky_type
snap = fetch_model_json_tcp("127.0.0.1", 9876, False)
bpy.ops.wm.read_factory_settings(use_empty=True)
imp = SceneImporter(); imp.set_filename(""); imp.skp_model = JsonModel(snap)
from blender_plugin.scene_importer import _default_prefs
prefs = _default_prefs()
print("ADHOC_SKY nishita_id=", _nishita_sky_type(), "setup_world_sky=", prefs.setup_world_sky, "model=", prefs.world_sky_model)
r = imp.load(bpy.context, filepath="", scenes_as_camera=False, import_camera=False, reuse_material=True,
             dedub_only=False, reuse_existing_groups=False, max_instance=1, dedub_type="VERTEX", import_scene="")
w = bpy.context.scene.world
sky = None
if w and w.node_tree:
    for n in w.node_tree.nodes:
        if n.bl_idname == "ShaderNodeTexSky": sky = n.sky_type
print("ADHOC_SKY result=", r, "applied_sky_type=", sky, "objects=", len(bpy.data.objects), "materials=", len(bpy.data.materials))
