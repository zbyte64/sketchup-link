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

# Assert the camera POSITION and VIEW DIRECTION match the stored scene, not just that it exists.
# The camera's world location is the eye; its view direction is -Z of its world matrix, which
# should point from the eye toward the target.
from mathutils import Vector  # noqa: E402

TOL = 1e-3  # metres; the snapshot is rounded to float precision
for scene in snap.get("scenes", []):
    if not scene.get("camera"):
        continue
    name = scene["name"]
    ob = bpy.data.objects[f"Cam: {name}"]
    eye = Vector(scene["camera"]["eye"])
    target = Vector(scene["camera"]["target"])

    loc = ob.matrix_world.translation
    if (loc - eye).length > TOL:
        fail(f"scene '{name}': camera at {tuple(round(v, 4) for v in loc)}, stored eye {tuple(round(v, 4) for v in eye)}")

    view_dir = -(ob.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0)))
    want_dir = (target - eye).normalized()
    if (view_dir.normalized() - want_dir).length > 1e-3:
        fail(f"scene '{name}': view direction {tuple(round(v, 4) for v in view_dir.normalized())} "
             f"does not point at stored target (expected {tuple(round(v, 4) for v in want_dir)})")

    # Up vector: the camera's local +Y, with the view direction removed, must point along the stored
    # up. Compare directions only, so the check does not depend on the stored up's length.
    up_want = Vector(scene["camera"]["up"]).normalized()
    cam_up = (ob.matrix_world.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()
    if cam_up.dot(up_want) < 1 - 1e-3:
        fail(f"scene '{name}': camera up {tuple(round(v, 4) for v in cam_up)} "
             f"does not match stored up {tuple(round(v, 4) for v in up_want)}")

    # Field of view: the importer sets the lens angle to (pi * fov / 180) * aspect_ratio, with the
    # importer's aspect ratio when the scene's is 0 (dynamic). Check the angle the code actually sets.
    import math
    fov = scene["camera"]["fov"]
    aspect = scene["camera"].get("aspect_ratio") or importer.aspect_ratio
    want_angle = math.pi * fov / 180 * aspect
    if abs(ob.data.angle - want_angle) > 1e-3:
        fail(f"scene '{name}': lens angle {ob.data.angle:.5f} rad does not match stored fov {fov} "
             f"(expected {want_angle:.5f} rad)")

print(f"LIVE-SCENE OK: position, direction, up and fov match for scenes {expected}")
sys.exit(0)
