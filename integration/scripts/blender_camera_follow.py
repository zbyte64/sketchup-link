import bpy, sys, queue, addon_utils
sys.path.insert(0, "/tmp/addons")
addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls
from blender_plugin.live_adapter import fetch_model_json_tcp
def sync_and_view():
    snap = fetch_model_json_tcp("172.17.0.1", 9876, False)
    cam = snap["camera"]
    from blender_plugin.live_adapter import JsonCamera
    ls._apply_viewport(JsonCamera(cam))
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            r3d = area.spaces[0].region_3d
            return tuple(round(v, 4) for v in r3d.view_matrix.to_translation())
print("CAMFOLLOW view1", sync_and_view(), flush=True)
print("CAMFOLLOW view2", sync_and_view(), flush=True)
