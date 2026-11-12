"""
Live-import smoke test: runs INSIDE Blender (`blender --background --python ...`).

Fetches a model snapshot from a running SketchUp link server, imports it with
the shared SceneImporter codepath, and reports what landed in the scene.

Environment:
    SKETCHUP_LINK_HOST  TCP host of the SketchUp link server (default 127.0.0.1)
    SKETCHUP_LINK_PORT  TCP port (default 9876)

Exit code 0 on success, non-zero on any failure, so the caller can gate on it.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import bpy  # type: ignore[import-not-found]  # noqa: E402  (Blender-only module)

HOST = os.environ.get("SKETCHUP_LINK_HOST", "127.0.0.1")
PORT = int(os.environ.get("SKETCHUP_LINK_PORT", "9876"))


from typing import NoReturn  # noqa: E402


def fail(msg: str) -> NoReturn:
    print(f"LIVE-IMPORT FAIL: {msg}")
    sys.exit(1)


# Make the repo a discoverable add-on location, then enable it through Blender's
# own addon system. This is what creates context.preferences.addons["blender_plugin"],
# which SceneImporter.load() reads. Calling register() alone does not create it.
import addon_utils  # type: ignore[import-not-found]  # noqa: E402  (Blender-only module)

# REPO is the directory that contains the `blender_plugin` package. Blender
# discovers add-ons from its script paths, so ensure REPO is on sys.path and
# refresh discovery before enabling by package name.
if REPO not in sys.path:
    sys.path.insert(0, REPO)
addon_utils.paths()

addon_utils.enable("blender_plugin", default_set=True, persistent=False)
if "blender_plugin" not in bpy.context.preferences.addons:
    fail("blender_plugin did not appear in context.preferences.addons after enable")

from blender_plugin.live_adapter import fetch_model_json_tcp, JsonModel  # noqa: E402
from blender_plugin.scene_importer import SceneImporter  # noqa: E402

print(f"Blender {bpy.app.version_string}; fetching http://{HOST}:{PORT}/model")

try:
    snapshot: dict = fetch_model_json_tcp(HOST, PORT, False)
except Exception as exc:  # noqa: BLE001
    fail(f"could not fetch /model: {exc}")

print("snapshot keys:", sorted(snapshot.keys())[:12])

# Clear the default scene so we can count what the import creates.
bpy.ops.wm.read_factory_settings(use_empty=True)

importer = SceneImporter()
importer.set_filename("")
importer.skp_model = JsonModel(snapshot)

options = dict(
    filepath="",
    scenes_as_camera=False,
    import_camera=False,
    reuse_material=True,
    dedub_only=False,
    reuse_existing_groups=False,
    max_instance=1,
    dedub_type="VERTEX",
    import_scene="",
)

result = None
try:
    result = importer.load(bpy.context, **options)
except Exception as exc:  # noqa: BLE001
    fail(f"SceneImporter.load raised: {exc!r}")

if result != {"FINISHED"}:
    fail(f"SceneImporter.load returned {result!r}")

objects = list(bpy.data.objects)
meshes = [o for o in objects if o.type == "MESH"]
materials = list(bpy.data.materials)

print(f"objects={len(objects)} meshes={len(meshes)} materials={len(materials)}")

if not meshes:
    fail("import produced no mesh objects")

# Fidelity: compare imported polygon count against the snapshot's triangles.
imported_polys = sum(len(o.data.polygons) for o in meshes)
imported_verts = sum(len(o.data.vertices) for o in meshes)
print(f"imported verts={imported_verts} polys={imported_polys}")

# Compare like with like: triangles of the definitions actually placed by the snapshot's
# top-level instances, against the polygons the importer built for those placements.
defs = snapshot.get("component_definitions", {})
placed = {e.get("definition_name") for e in snapshot.get("entities", [])
          if e.get("type") == "ComponentInstance"}
source_triangles = 0
for name in placed:
    for e in defs.get(name, {}).get("entities", []):
        if e.get("type") == "Face":
            source_triangles += len(e.get("triangles", []))
print(f"placed definitions={sorted(placed)} source triangles={source_triangles}")

if imported_polys == 0:
    fail("imported mesh has zero polygons")

if source_triangles and imported_polys < source_triangles:
    fail(f"imported polygons {imported_polys} fewer than placed source triangles {source_triangles}")

print("LIVE-IMPORT OK")
sys.exit(0)
