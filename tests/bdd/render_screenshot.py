#!/usr/bin/env blender --python
"""
Blender headless entry point for BDD screenshot capture.

Usage:
    blender --background --python render_screenshot.py -- <model_json_path> <screenshot_path>

The script:
  1. Reads the model JSON from file
  2. Imports it via SceneImporter.load()
  3. Frames the camera to show all geometry
  4. Adds default lighting
  5. Renders a solid viewport-style PNG
"""
import json
import math
import os
import site
import sys
import types

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_USER_SITE = site.getusersitepackages()
if _USER_SITE and _USER_SITE not in sys.path:
    sys.path.insert(0, _USER_SITE)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_DIR = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", ".."))

if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

# ---------------------------------------------------------------------------
# Stub the Cython sketchup module (same pattern as run_blender_tests.py)
# ---------------------------------------------------------------------------
_sketchup_stub = types.ModuleType("blender_plugin.sketchup")
_sketchup_stub.__package__ = "blender_plugin"


class _StubModel:
    @staticmethod
    def from_file(path):
        return None


_sketchup_stub.Model = _StubModel
sys.modules["blender_plugin.sketchup"] = _sketchup_stub

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_scene_bounds():
    """Return (min_corner, max_corner) of all visible mesh objects."""
    import bpy  # noqa: E402
    from mathutils import Vector
    min_c = [float("inf")] * 3
    max_c = [float("-inf")] * 3
    found = False

    for obj in bpy.data.objects:
        if obj.type == "MESH":
            for corner in obj.bound_box:
                world_corner = obj.matrix_world @ Vector(corner)
                for axis in range(3):
                    min_c[axis] = min(min_c[axis], world_corner[axis])
                    max_c[axis] = max(max_c[axis], world_corner[axis])
            found = True

    if not found:
        # No meshes — return a unit cube centered at origin
        return (-1, -1, -1), (1, 1, 1)

    return tuple(min_c), tuple(max_c)


def _setup_camera(context, bbox_min, bbox_max):
    """Create or reuse a camera that frames the bounding box."""
    import bpy  # noqa: E402

    center = (
        (bbox_min[0] + bbox_max[0]) / 2,
        (bbox_min[1] + bbox_max[1]) / 2,
        (bbox_min[2] + bbox_max[2]) / 2,
    )
    size = max(
        bbox_max[0] - bbox_min[0],
        bbox_max[1] - bbox_min[1],
        bbox_max[2] - bbox_min[2],
        0.001,
    )

    # Remove any existing cameras
    for obj in bpy.data.objects:
        if obj.type == "CAMERA":
            bpy.data.objects.remove(obj, do_unlink=True)

    # Create camera
    cam_data = bpy.data.cameras.new("ScreenshotCam")
    cam_obj = bpy.data.objects.new("ScreenshotCam", cam_data)
    context.collection.objects.link(cam_obj)

    # Position camera to frame the bounding box
    # Use an isometric-ish angle looking down at the scene
    distance = size * 2.5
    angle_rad = math.radians(35)
    cam_obj.location = (
        center[0] + distance * math.cos(angle_rad),
        center[1] - distance * math.cos(angle_rad),
        center[2] + distance * math.sin(angle_rad),
    )

    # Point camera at center
    direction = (
        center[0] - cam_obj.location[0],
        center[1] - cam_obj.location[1],
        center[2] - cam_obj.location[2],
    )
    cam_obj.rotation_euler = _look_at_rotation(direction)

    # Set as active camera
    context.scene.camera = cam_obj

    return cam_obj


def _look_at_rotation(direction):
    """Compute Euler rotation angles (XYZ) for a camera looking along `direction`."""
    x, y, z = direction
    length = math.sqrt(x * x + y * y + z * z)
    if length < 1e-8:
        return (0, 0, 0)

    # Spherical coordinates
    theta = math.atan2(y, x)  # azimuth
    phi = math.acos(z / length)  # inclination

    # XYZ Euler: Align -Z axis to direction
    return (phi - math.pi / 2, 0, -theta + math.pi / 2)


def _setup_lighting(context, bbox_min, bbox_max):
    """Add default area lights for solid viewport rendering."""
    import bpy  # noqa: E402

    center = (
        (bbox_min[0] + bbox_max[0]) / 2,
        (bbox_min[1] + bbox_max[1]) / 2,
        (bbox_min[2] + bbox_max[2]) / 2,
    )
    size = max(
        bbox_max[0] - bbox_min[0],
        bbox_max[1] - bbox_min[1],
        bbox_max[2] - bbox_min[2],
        0.001,
    )

    # Remove existing lights
    for obj in bpy.data.objects:
        if obj.type == "LIGHT":
            bpy.data.objects.remove(obj, do_unlink=True)

    # Key light (above and to the right)
    key_light_data = bpy.data.lights.new("KeyLight", type="AREA")
    key_light_data.energy = size * 200  # Scale energy to scene size
    key_light_data.size = size * 0.5
    key_obj = bpy.data.objects.new("KeyLight", key_light_data)
    key_obj.location = (
        center[0] + size * 1.5,
        center[1] - size * 1.0,
        center[2] + size * 2.0,
    )
    key_obj.rotation_euler = (math.radians(60), 0, math.radians(45))
    context.collection.objects.link(key_obj)

    # Fill light (opposite side, dimmer)
    fill_light_data = bpy.data.lights.new("FillLight", type="AREA")
    fill_light_data.energy = size * 100
    fill_light_data.size = size * 0.3
    fill_obj = bpy.data.objects.new("FillLight", fill_light_data)
    fill_obj.location = (
        center[0] - size * 1.2,
        center[1] + size * 1.5,
        center[2] + size * 1.0,
    )
    fill_obj.rotation_euler = (math.radians(30), 0, math.radians(-45))
    context.collection.objects.link(fill_obj)

    # Back light (rim light)
    rim_light_data = bpy.data.lights.new("RimLight", type="AREA")
    rim_light_data.energy = size * 50
    rim_light_data.size = size * 0.2
    rim_obj = bpy.data.objects.new("RimLight", rim_light_data)
    rim_obj.location = (
        center[0] - size * 0.5,
        center[1] + size * 2.0,
        center[2] + size * 0.5,
    )
    rim_obj.rotation_euler = (math.radians(10), 0, math.radians(135))
    context.collection.objects.link(rim_obj)


def _setup_render_settings(context, screenshot_path):
    """Configure render settings for a solid viewport render."""
    import bpy  # noqa: E402

    scene = context.scene

    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100
    scene.render.filepath = screenshot_path
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"

    # World background (subtle gray)
    world = scene.world
    if world:
        world.use_nodes = False
        world.color = (0.05, 0.05, 0.05)  # Dark gray


def main():
    import bpy  # noqa: E402

    # Parse arguments after '--'
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if len(args) < 2:
        print(json.dumps({"status": "error", "message": "Usage: -- <model_json_path> <screenshot_path>"}))
        sys.exit(1)

    model_json_path = args[0]
    screenshot_path = args[1]

    if not os.path.exists(model_json_path):
        print(json.dumps({"status": "error", "message": f"Model JSON not found: {model_json_path}"}))
        sys.exit(1)

    # Read model JSON
    with open(model_json_path) as f:
        model_dict = json.load(f)

    # Register the addon
    try:
        if "blender_plugin" not in bpy.context.preferences.addons:
            bpy.ops.preferences.addon_enable(module="blender_plugin")
    except Exception:
        pass  # May fail headless; SceneImporter handles missing prefs

    from blender_plugin.live_adapter import JsonModel  # noqa: E402
    from blender_plugin.scene_importer import SceneImporter  # noqa: E402

    try:
        # Wrap and import
        model = JsonModel(model_dict)
        importer = SceneImporter()
        importer.skp_model = model
        context = bpy.context

        options = {
            "reuse_material": True,
            "reuse_existing_groups": True,
            "max_instance": 200,
            "import_scene": None,
            "scenes_as_camera": False,
            "import_camera": False,
            "dedub_only": False,
            "dedub_type": "VERTEX",
        }
        result = importer.load(context, **options)

        if result != {"FINISHED"}:
            print(json.dumps({"status": "error", "message": f"Import returned: {result}"}))
            sys.exit(1)

        # Compute scene bounds for camera/lighting
        bbox_min, bbox_max = _compute_scene_bounds()

        # Set up camera, lighting, render settings
        _setup_camera(context, bbox_min, bbox_max)
        _setup_lighting(context, bbox_min, bbox_max)
        _setup_render_settings(context, screenshot_path)

        # Ensure output directory exists
        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)

        # Render
        bpy.ops.render.render(write_still=True)

        if os.path.exists(screenshot_path):
            print(json.dumps({"status": "passed", "screenshot": screenshot_path, "size_bytes": os.path.getsize(screenshot_path)}))
            sys.exit(0)
        else:
            print(json.dumps({"status": "error", "message": "Render completed but screenshot file not found"}))
            sys.exit(1)

    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
