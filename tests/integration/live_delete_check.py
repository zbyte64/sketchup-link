"""
Live delete smoke test: runs INSIDE Blender (`blender --background --python ...`).

Verifies that re-importing a live snapshot removes objects that the importer
created for entities no longer present, while untagged user objects survive.

Steps:
  1. Fetch a snapshot A from the SketchUp link server.
  2. Add an untagged user object ("USER_KEEP") to the scene.
  3. Import snapshot A; then add a synthetic stale entity to A's data and
     import it, so an importer-created object exists for it ("STALE_ENTITY").
  4. Import snapshot B = A with that entity removed.
  5. Assert the stale object is gone and the untagged user object survives.

Environment:
    SKETCHUP_LINK_HOST  TCP host of the SketchUp link server (default 127.0.0.1)
    SKETCHUP_LINK_PORT  TCP port (default 9876)

Exit code 0 on success, non-zero on any failure.
"""

import copy
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
    print(f"LIVE-DELETE FAIL: {msg}")
    sys.exit(1)


import addon_utils  # type: ignore[import-not-found]  # noqa: E402  (Blender-only module)

addon_utils.paths()
addon_utils.enable("blender_plugin", default_set=True, persistent=False)
if "blender_plugin" not in bpy.context.preferences.addons:
    fail("blender_plugin did not appear in context.preferences.addons after enable")

from blender_plugin.live_adapter import fetch_model_json_tcp, JsonModel  # noqa: E402
from blender_plugin.scene_importer import SceneImporter  # noqa: E402

STALE_NAME = "STALE_ENTITY"
USER_NAME = "USER_KEEP"

print(f"Blender {bpy.app.version_string}; fetching http://{HOST}:{PORT}/model")

try:
    snapshot_a: dict = fetch_model_json_tcp(HOST, PORT, False)
except Exception as exc:  # noqa: BLE001
    fail(f"could not fetch /model: {exc}")

OPTIONS = dict(
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


def run_import(snapshot: dict) -> None:
    importer = SceneImporter()
    importer.set_filename("")
    importer.skp_model = JsonModel(snapshot)
    try:
        result = importer.load(bpy.context, **OPTIONS)
    except Exception as exc:  # noqa: BLE001
        fail(f"SceneImporter.load raised: {exc!r}")
    if result != {"FINISHED"}:
        fail(f"SceneImporter.load returned {result!r}")


# Fresh scene so counts are deterministic.
bpy.ops.wm.read_factory_settings(use_empty=True)

# An untagged user object that the importer must never delete.
user_ob = bpy.data.objects.new(USER_NAME, None)
bpy.context.scene.collection.objects.link(user_ob)

# Snapshot A: the real model plus a synthetic extra entity (a stale candidate).
snapshot_a = copy.deepcopy(snapshot_a)
extra = copy.deepcopy(next(
    e for d in snapshot_a.get("component_definitions", {}).values()
    for e in d.get("entities", []) if e.get("type") == "Face"
))
stale_group = {
    "type": "Group",
    "persistent_id": STALE_NAME,
    "name": STALE_NAME,
    "layer": "Furniture",
    "transformation": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
    "entities": [extra],
}
snapshot_a.setdefault("entities", []).append(stale_group)

run_import(snapshot_a)

stale_before = [o.name for o in bpy.data.objects if o.get("skp_link_import") and STALE_NAME in o.name]
print(f"after A: objects={len(bpy.data.objects)} stale_candidates={stale_before}")
if not stale_before:
    fail("snapshot A did not produce an importer-tagged object for the synthetic entity")

# Snapshot B: same model, the synthetic entity removed.
snapshot_b = copy.deepcopy(snapshot_a)
snapshot_b["entities"] = [e for e in snapshot_b.get("entities", []) if e.get("persistent_id") != STALE_NAME]

run_import(snapshot_b)

names = {o.name for o in bpy.data.objects}
print(f"after B: objects={len(bpy.data.objects)}")

stale_left = [n for n in names if STALE_NAME in n]
if stale_left:
    fail(f"stale object(s) survived re-import: {stale_left}")

if USER_NAME not in names:
    fail("untagged user object was deleted by re-import")

if USER_NAME in {o.name for o in bpy.data.objects if o.get("skp_link_import")}:
    fail("untagged user object was wrongly tagged")

print("LIVE-DELETE OK")
sys.exit(0)
