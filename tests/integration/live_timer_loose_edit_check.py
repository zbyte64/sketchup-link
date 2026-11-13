"""
Live timer loose-geometry edit check (functionality gap: loose top-level geometry was not pushed). Runs INSIDE
Blender:

    blender --background --factory-startup --python tests/integration/live_timer_loose_edit_check.py

Loose top-level faces import as one "_(Loose Entity)" object with no SketchUp id of its own, but each polygon
names its SketchUp face in skp_face_id. Edits a corner of the back-painted loose face in Blender, runs the real
timer, and asserts that SketchUp reshaped exactly that face at the top level: its old id is gone, one new
top-level face has the moved corner and keeps its back material, the top-level face count is unchanged, and the
other loose face is untouched. The reference model is restored before and after.
"""
import json
import logging
import os
import queue
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
for p in (REPO, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import addon_utils  # noqa: E402
import bpy  # noqa: E402
import reference_reset  # noqa: E402

HOST = os.environ.get("SKETCHUP_LINK_HOST", "127.0.0.1")
PORT = int(os.environ.get("SKETCHUP_LINK_PORT", "9876"))
SHIFT = 0.05  # metres, outward in +X: the quad stays convex


def fail(msg):
    print(f"LIVE-TIMER-LOOSE FAIL: {msg}")
    sys.exit(1)


def top_faces():
    d = json.loads(urllib.request.urlopen(f"http://{HOST}:{PORT}/model", timeout=30).read())
    return {e["persistent_id"]: e for e in d["entities"] if e.get("type") == "Face"}


addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402


def run_timer():
    _snap = fetch_model_json_tcp(HOST, PORT, False)
    _snap["two_way_enabled"] = True  # this check exercises two-way editing
    ls._sync_state["queue"].put(_snap)
    ls._sync_timer()


reference_reset.reset()
reference_reset.verify()
status = 1
try:
    ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
    ls._sync_state["running"] = True
    ls._sync_state["queue"] = queue.SimpleQueue()
    run_timer()  # import and record the baseline

    before = top_faces()
    target = next((pid for pid, f in before.items() if not f.get("material") and f.get("back_material")), None)
    other = next((pid for pid, f in before.items() if f.get("material")), None)
    if target is None or other is None:
        fail(f"the reference model does not have the two loose faces this check edits: {before}")

    ob = next((o for o in bpy.data.objects if o.name.startswith("_(Loose Entity)")), None)
    if ob is None:
        fail("no _(Loose Entity) object after the import")
    layer = ob.data.attributes.get("skp_face_id")
    if layer is None:
        fail("the loose-geometry mesh has no skp_face_id layer")
    polys = [p for p in ob.data.polygons if int(layer.data[p.index].value) == target]
    if not polys:
        fail(f"no polygon names the target face {target}")
    vids = {v for p in polys for v in p.vertices}
    corner = max(vids, key=lambda i: (ob.data.vertices[i].co.x, ob.data.vertices[i].co.y))
    moved_to = (ob.matrix_world @ ob.data.vertices[corner].co).copy()
    moved_to.x += SHIFT
    ob.data.vertices[corner].co.x += SHIFT
    ob.data.update()

    pushed = {"ok": None}

    class _Watch(logging.Handler):
        def emit(self, record):
            msg = record.getMessage()
            if "reshaped SketchUp face" in msg:
                pushed["ok"] = True
            if "reshape push failed" in msg:
                pushed["ok"] = False

    logging.getLogger("blender_plugin").addHandler(_Watch())
    run_timer()
    if pushed["ok"] is not True:
        fail("the timer did not reshape the loose face: the push failed or was never sent")

    after = top_faces()
    if len(after) != len(before):
        fail(f"the top-level face count changed from {len(before)} to {len(after)}")
    if target in after:
        fail(f"face {target} was not reshaped: its id is still at the top level")
    if other not in after:
        fail(f"the other loose face {other} was changed, but it was not edited")
    new = [after[pid] for pid in set(after) - set(before)]
    if len(new) != 1:
        fail(f"expected one new top-level face, got {len(new)}")
    face = new[0]
    if face.get("back_material") != "Blue":
        fail(f"the reshaped face lost its back material: {face.get('back_material')!r}")
    if not any(all(abs(a - b) < 1e-3 for a, b in zip(v, moved_to)) for v in face["outer_loop"]):
        fail(f"no corner of the reshaped face is at the edited position {tuple(round(c, 3) for c in moved_to)}")

    status = 0
    print(f"LIVE-TIMER-LOOSE OK: loose face {target} reshaped at the top level to {face['persistent_id']}, "
          f"corner moved, back material kept, other face untouched")
finally:
    reference_reset.reset()
    reference_reset.verify()
sys.exit(status)
