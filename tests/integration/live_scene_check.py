"""
Live scene import check (Blender). Imports the live snapshot with scenes_as_camera on and
asserts that a camera is created for each scene that has a view. Run inside Blender:

    blender --background --factory-startup --python tests/integration/live_scene_check.py

Exit code 0 on success. Scenes are found by name from the snapshot, not by index.
"""
import os
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
    print(f"LIVE-SCENE FAIL: {msg}")
    sys.exit(1)


addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin.live_adapter import JsonModel, fetch_model_json_tcp  # noqa: E402
from blender_plugin.scene_importer import SceneImporter  # noqa: E402

snap = fetch_model_json_tcp(HOST, PORT, False)
expected = [s["name"] for s in snap.get("scenes", []) if s.get("camera")]
if not expected:
    fail("snapshot has no scenes with a camera; the reference model should provide them")

importer = SceneImporter()
importer.set_filename("")
importer.skp_model = JsonModel(snap)
importer.load(
    bpy.context,
    filepath="", scenes_as_camera=True, import_camera=False, reuse_material=True,
    dedub_only=False, reuse_existing_groups=False, max_instance=1,
    dedub_type="VERTEX", import_scene="",
)

cameras = {o.name for o in bpy.data.objects if o.type == "CAMERA"}
for name in expected:
    if f"Cam: {name}" not in cameras:
        fail(f"no Blender camera 'Cam: {name}' for scene '{name}'; cameras are {sorted(cameras)}")

print(f"LIVE-SCENE OK: cameras for scenes {expected}")
sys.exit(0)
