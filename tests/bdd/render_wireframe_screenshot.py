#!/usr/bin/env blender --python
"""
Blender headless entry point for BDD wireframe screenshot capture.

Usage:
    blender --background --python render_wireframe_screenshot.py -- <model_json_path> <screenshot_path>

The script:
  1. Reads the model JSON from file
  2. Imports it via SceneImporter.load()
  3. Adds a temporary Wireframe modifier to all mesh objects
  4. Frames the camera to show all geometry
  5. Adds minimal lighting
  6. Renders a wireframe-overlay PNG
  7. Removes the Wireframe modifiers (clean exit)
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
# Stub the Cython sketchup module (same pattern as render_screenshot.py)
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
    return cam_obj


def _look_at_rotation(direction):
    """Compute Euler rotation angles (XYZ) for a camera looking along `direction`.
    Uses orthonormal basis construction for correct Blender camera alignment.
    """
    from mathutils import Matrix, Vector
    forward = Vector(direction).normalized()
    up_ref = Vector((0, 0, 1))
    right = forward.cross(up_ref)
    if right.length_squared < 1e-12:
        right = Vector((1, 0, 0))
    else:
        right.normalize()
    up = right.cross(forward).normalized()
    # Build a 3×3 rotation matrix (columns = camera axes in world space).
    mat = Matrix((
        (right.x, up.x, -forward.x),
        (right.y, up.y, -forward.y),
        (right.z, up.z, -forward.z),
    ))
    return mat.to_euler("XYZ")

def _setup_lighting(context, bbox_min, bbox_max):
    """Add area lights for wireframe render (keep it clean, no harsh shadows)."""
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

    for obj in bpy.data.objects:
        if obj.type == "LIGHT":
            bpy.data.objects.remove(obj, do_unlink=True)

    # Key light (diffuse, not too strong)
    key_light_data = bpy.data.lights.new("KeyLight", type="AREA")
    key_light_data.energy = size * 150
    key_light_data.size = size * 0.5
    key_obj = bpy.data.objects.new("KeyLight", key_light_data)
    key_obj.location = (
        center[0] + size * 1.5,
        center[1] - size * 1.0,
        center[2] + size * 2.0,
    )
    key_obj.rotation_euler = (math.radians(60), 0, math.radians(45))
    context.collection.objects.link(key_obj)

    # Fill light (opposite side)
    fill_light_data = bpy.data.lights.new("FillLight", type="AREA")
    fill_light_data.energy = size * 80
    fill_light_data.size = size * 0.3
    fill_obj = bpy.data.objects.new("FillLight", fill_light_data)
    fill_obj.location = (
        center[0] - size * 1.2,
        center[1] + size * 1.5,
        center[2] + size * 1.0,
    )
    fill_obj.rotation_euler = (math.radians(30), 0, math.radians(-45))
    context.collection.objects.link(fill_obj)


def _add_wireframe_modifiers(bbox_min, bbox_max):
    """Add Wireframe modifier to all mesh objects for edge overlay.

    Uses 'use_replace=False' so the wireframe geometry overlays the
    original faces. The wire thickness scales with scene size.
    """
    import bpy  # noqa: E402

    size = max(
        bbox_max[0] - bbox_min[0],
        bbox_max[1] - bbox_min[1],
        bbox_max[2] - bbox_min[2],
        0.001,
    )
    # Wire thickness: 0.3% of scene size, minimum floor of 0.001
    wire_thickness = max(size * 0.003, 0.001)

    added_mods = []
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            mod = obj.modifiers.new(name="_bdd_wireframe", type="WIREFRAME")
            mod.thickness = wire_thickness
            mod.use_replace = False
            mod.use_even_offset = False
            mod.use_relative_offset = False
            mod.use_boundary = True
            added_mods.append(mod)
    return added_mods, wire_thickness


def _remove_wireframe_modifiers(modifiers):
    """Remove the wireframe modifiers we added."""
    import bpy  # noqa: E402
    for mod in modifiers:
        if mod is not None:
            obj = mod.id_data
            obj.modifiers.remove(mod)


def _setup_render_settings(context, screenshot_path, wire_thickness):
    """Configure render settings for wireframe view."""
    import bpy  # noqa: E402

    scene = context.scene

    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100
    scene.render.filepath = screenshot_path
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"

    # Workbench shading for wireframe overlay
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"

    # Light background for wireframe contrast
    world = scene.world
    if world:
        world.use_nodes = False
        world.color = (0.95, 0.95, 0.95)  # Near-white background


def main():
    import bpy  # noqa: E402
    import traceback  # noqa: E402

    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(args) < 2:
        print(json.dumps({"status": "error", "message": "Usage: -- <model_json_path> <screenshot_path>"}))
        sys.exit(1)

    model_json_path = args[0]
    screenshot_path = args[1]

    if not os.path.exists(model_json_path):
        print(json.dumps({"status": "error", "message": f"Model JSON not found: {model_json_path}"}))
        sys.exit(1)

    with open(model_json_path) as f:
        model_dict = json.load(f)

    try:
        if "blender_plugin" not in bpy.context.preferences.addons:
            bpy.ops.preferences.addon_enable(module="blender_plugin")
    except Exception:
        pass

    from blender_plugin.live_adapter import JsonModel  # noqa: E402
    from blender_plugin.scene_importer import SceneImporter  # noqa: E402

    try:
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

        # Diagnostics: log post-import scene state
        mesh_count = sum(1 for o in bpy.data.objects if o.type == "MESH")
        total_objs = len(bpy.data.objects)
        print(json.dumps({
            "status": "debug",
            "phase": "post_import",
            "mesh_objects": mesh_count,
            "total_objects": total_objs,
            "collections": [c.name for c in bpy.data.collections],
        }), flush=True)
        bbox_min, bbox_max = _compute_scene_bounds()
        print(json.dumps({
            "status": "debug",
            "phase": "bounds",
            "bbox_min": list(bbox_min),
            "bbox_max": list(bbox_max),
        }), flush=True)

        # If no mesh objects found, add a diagnostic cube to verify render
        if bbox_min == (-1, -1, -1) and bbox_max == (1, 1, 1) and mesh_count == 0:
            print(json.dumps({"status": "warning", "message": "No mesh objects found — creating diagnostic cube"}), flush=True)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 1))
            cube = bpy.context.object
            cube.name = "DiagnosticCube"
            bbox_min, bbox_max = (-0.5, -0.5, -0.5), (0.5, 0.5, 0.5)

        _setup_camera(context, bbox_min, bbox_max)
        _setup_lighting(context, bbox_min, bbox_max)

        # Add Wireframe modifiers and capture thickness for logging
        modifiers_added, wire_thickness = _add_wireframe_modifiers(bbox_min, bbox_max)
        _setup_render_settings(context, screenshot_path, wire_thickness)

        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)

        bpy.ops.render.render(write_still=True)

        # Remove the temporary modifiers
        _remove_wireframe_modifiers(modifiers_added)

        if os.path.exists(screenshot_path):
            print(json.dumps({
                "status": "passed",
                "screenshot": screenshot_path,
                "size_bytes": os.path.getsize(screenshot_path),
                "wire_thickness": wire_thickness,
            }))
            sys.exit(0)
        else:
            print(json.dumps({"status": "error", "message": "Render completed but screenshot file not found"}))
            sys.exit(1)

    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
