"""Frame the Blender viewport on a SketchUp scene's camera, and capture it.

Runs inside a Blender GUI session (display :99). It imports the live snapshot with
scenes_as_camera on, makes the named scene's camera the viewport's camera, and captures the
screen to /tmp/scene_view.xwd. A failure to find the camera is reported, not ignored.
"""
import os
import subprocess
import sys

import addon_utils
import bpy

HOST = os.environ.get("SKETCHUP_LINK_HOST", "172.17.0.1")
PORT = int(os.environ.get("SKETCHUP_LINK_PORT", "9876"))
SCENE = os.environ.get("SCENE_NAME", "Cube front")
ADDON_ROOT = os.environ.get("SKP_ADDON_ROOT", "/tmp/addons")

sys.path.insert(0, ADDON_ROOT)
addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin.live_adapter import JsonModel, fetch_model_json_tcp  # noqa: E402
from blender_plugin.scene_importer import SceneImporter  # noqa: E402


def run():
    snap = fetch_model_json_tcp(HOST, PORT, False)
    imp = SceneImporter()
    imp.set_filename("")
    imp.skp_model = JsonModel(snap)
    imp.load(
        bpy.context,
        filepath="", scenes_as_camera=True, import_camera=False, reuse_material=True,
        dedub_only=False, reuse_existing_groups=False, max_instance=1,
        dedub_type="VERTEX", import_scene="",
    )
    cam = bpy.data.objects.get(f"Cam: {SCENE}")
    if cam is None:
        print(f"SCENEVIEW FAIL no camera 'Cam: {SCENE}'", flush=True)
        return None
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            area.spaces[0].region_3d.view_perspective = "CAMERA"
            bpy.context.scene.camera = cam
            area.tag_redraw()
    print(f"SCENEVIEW framed on {cam.name}", flush=True)
    return None


def capture_later():
    subprocess.run(["bash", "-lc", "DISPLAY=:99 xwd -root -silent > /tmp/scene_view.xwd"], check=True)
    print("SCENEVIEW captured", flush=True)
    return None


STEP = {"n": 0}


def step():
    STEP["n"] += 1
    if STEP["n"] == 1:
        run()
        return 6.0
    if STEP["n"] == 2:
        capture_later()
        return None
    return None


bpy.app.timers.register(step, first_interval=12.0)
