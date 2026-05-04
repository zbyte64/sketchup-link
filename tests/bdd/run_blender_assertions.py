#!/usr/bin/env python3
"""
Blender headless entry point for BDD assertion scripts.

Usage (inside Blender's Python):
    blender --background --python run_blender_assertions.py -- <socket_path> <assertion_script>

The assertion script is a Python file containing functions that receive a
`scene_importer` instance and a `json_model` dict. It must define:

    def run_assertions(importer, model_dict, screenshot_path=None):
        \"\"\"Execute assertions. Raise AssertionError on failure.\"\"\"

Exit code: 0 on success, 1 on assertion failure.
"""
import json
import os
import sys
import tempfile
import types
import site

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_USER_SITE = site.getusersitepackages()
if _USER_SITE and _USER_SITE not in sys.path:
    sys.path.insert(0, _USER_SITE)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_DIR = os.path.normpath(os.path.join(_SCRIPT_DIR, '..', '..'))

if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

# ---------------------------------------------------------------------------
# Stub the Cython sketchup module (like run_blender_tests.py)
# ---------------------------------------------------------------------------

_sketchup_stub = types.ModuleType('blender_plugin.sketchup')
_sketchup_stub.__package__ = 'blender_plugin'


class _StubModel:
    @staticmethod
    def from_file(path):
        return None


_sketchup_stub.Model = _StubModel
sys.modules['blender_plugin.sketchup'] = _sketchup_stub


def main():
    # Parse arguments after '--'
    args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    if len(args) < 2:
        print(json.dumps({'status': 'error', 'message': 'Usage: -- <socket_path> <assertion_script> [screenshot_path]'}))
        sys.exit(1)

    socket_path = args[0]
    assertion_script = args[1]
    screenshot_path = args[2] if len(args) > 2 else None

    if not os.path.exists(assertion_script):
        print(json.dumps({'status': 'error', 'message': f'Assertion script not found: {assertion_script}'}))
        sys.exit(1)

    # Import Blender modules
    import bpy  # noqa: E402

    # Register the addon so prefs are available
    try:
        if 'blender_plugin' not in bpy.context.preferences.addons:
            bpy.ops.preferences.addon_enable(module='blender_plugin')
    except Exception:
        pass  # May fail headless; SceneImporter handles missing prefs

    from blender_plugin.live_adapter import fetch_model_json, JsonModel  # noqa: E402
    from blender_plugin.scene_importer import SceneImporter  # noqa: E402

    try:
        # Fetch model JSON from socket
        model_dict = fetch_model_json(socket_path)
        model = JsonModel(model_dict)

        # Run SceneImporter.load()
        importer = SceneImporter()
        importer.skp_model = model
        context = bpy.context

        options = {
            'reuse_material': True,
            'reuse_existing_groups': True,
            'max_instance': 200,
            'import_scene': None,
            'scenes_as_camera': False,
            'import_camera': False,
            'dedub_only': False,
            'dedub_type': 'VERTEX',
        }
        result = importer.load(context, **options)

        if result == {'FINISHED'}:
            # Set up camera and lighting for screenshot
            if screenshot_path:
                _setup_camera_and_lighting(context)
                _setup_render(context, screenshot_path)
            # Load and execute the assertion script
            spec = importlib.util.spec_from_file_location('bdd_assertions', assertion_script)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            mod.run_assertions(importer, model_dict, screenshot_path=screenshot_path)

            print(json.dumps({'status': 'passed', 'screenshot': screenshot_path}))
            sys.exit(0)
        else:
            print(json.dumps({'status': 'error', 'message': f'Import returned unexpected result: {result}'}))
            sys.exit(1)

    except AssertionError as e:
        print(json.dumps({'status': 'failed', 'message': str(e)}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({'status': 'error', 'message': str(e)}))
        sys.exit(1)


import importlib  # noqa: E402 — delayed import for main()
# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


def _compute_scene_bounds():
    """Return (min_corner, max_corner) of all visible mesh objects."""
    import bpy

    from mathutils import Vector
    min_c = [float("inf")] * 3
    max_c = [float("-inf")] * 3
    found = False
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            for corner in obj.bound_box:
            world_corner = obj.matrix_world @ Vector(corner)
                    min_c[axis] = min(min_c[axis], world_corner[axis])
                    max_c[axis] = max(max_c[axis], world_corner[axis])
            found = True
    if not found:
        return (-1, -1, -1), (1, 1, 1)
    return tuple(min_c), tuple(max_c)


def _look_at_rotation(direction):
    """Compute Euler rotation angles (XYZ) for a camera looking along `direction`."""
    import math
    x, y, z = direction
    length = math.sqrt(x * x + y * y + z * z)
    if length < 1e-8:
        return 0, 0, 0
    theta = math.atan2(y, x)
    phi = math.acos(z / length)
    return (phi - math.pi / 2, 0, -theta + math.pi / 2)


def _setup_camera_and_lighting(context):
    """Set up camera and lighting for a solid viewport render."""
    import bpy
    import math

    bbox_min, bbox_max = _compute_scene_bounds()
    center = (
        (bbox_min[0] + bbox_max[0]) / 2,
        (bbox_min[1] + bbox_max[1]) / 2,
        (bbox_min[2] + bbox_max[2]) / 2,
    )
    size = max(bbox_max[0] - bbox_min[0], bbox_max[1] - bbox_min[1], bbox_max[2] - bbox_min[2], 0.001)

    # Camera
    for obj in bpy.data.objects:
        if obj.type == "CAMERA":
            bpy.data.objects.remove(obj, do_unlink=True)
    cam_data = bpy.data.cameras.new("ScreenshotCam")
    cam_obj = bpy.data.objects.new("ScreenshotCam", cam_data)
    context.collection.objects.link(cam_obj)
    distance = size * 2.5
    angle_rad = math.radians(35)
    cam_obj.location = (
        center[0] + distance * math.cos(angle_rad),
        center[1] - distance * math.cos(angle_rad),
        center[2] + distance * math.sin(angle_rad),
    )
    direction = (
        center[0] - cam_obj.location[0],
        center[1] - cam_obj.location[1],
        center[2] - cam_obj.location[2],
    )
    cam_obj.rotation_euler = _look_at_rotation(direction)
    context.scene.camera = cam_obj

    # Lighting
    for obj in bpy.data.objects:
        if obj.type == "LIGHT":
            bpy.data.objects.remove(obj, do_unlink=True)
    key_data = bpy.data.lights.new("KeyLight", type="AREA")
    key_data.energy = size * 200
    key_data.size = size * 0.5
    key_obj = bpy.data.objects.new("KeyLight", key_data)
    key_obj.location = (center[0] + size * 1.5, center[1] - size * 1.0, center[2] + size * 2.0)
    key_obj.rotation_euler = (math.radians(60), 0, math.radians(45))
    context.collection.objects.link(key_obj)
    fill_data = bpy.data.lights.new("FillLight", type="AREA")
    fill_data.energy = size * 100
    fill_data.size = size * 0.3
    fill_obj = bpy.data.objects.new("FillLight", fill_data)
    fill_obj.location = (center[0] - size * 1.2, center[1] + size * 1.5, center[2] + size * 1.0)
    fill_obj.rotation_euler = (math.radians(30), 0, math.radians(-45))
    context.collection.objects.link(fill_obj)


def _setup_render(context, screenshot_path):
    """Configure render settings and render viewport to PNG."""
    import bpy
    import os

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
    world = scene.world
    if world:
        world.use_nodes = False
        world.color = (0.05, 0.05, 0.05)
    os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
    bpy.ops.render.render(write_still=True)

if __name__ == '__main__':
    main()
