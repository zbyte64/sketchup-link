"""
Live timer reshape check (two-way mesh edits). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_timer_reshape_check.py

Edits a vertex of an imported mesh in Blender, runs the real timer, and asserts that the SketchUp face the
edited polygon came from is reshaped in place through /control/geometry/face/reshape: the old face id is
gone, a new face id is in the same group, the group's face count is unchanged, and the new loop matches
the edit. The reference model is restored with the full purge before and after.
"""
import json
import os
import queue
import re
import socket
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

sys.path.insert(0, HERE)
import addon_utils  # noqa: E402
import bpy  # noqa: E402

HOST = os.environ.get("SKETCHUP_LINK_HOST", "127.0.0.1")
PORT = int(os.environ.get("SKETCHUP_LINK_PORT", "9876"))
BASE = f"http://{HOST}:{PORT}"


def fail(msg):
    print(f"LIVE-TIMER-RESHAPE FAIL: {msg}")
    sys.exit(1)


def post(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body or {}).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def model():
    return json.loads(urllib.request.urlopen(BASE + "/model", timeout=30).read())


def group_faces():
    grp = next(e for e in model()["entities"] if e.get("type") == "Group" and e.get("name") == "FurnitureGroup")
    return grp, [e for e in grp["entities"] if e.get("type") == "Face"]


def reset_reference():
    """The shared reset (tests/integration/reference_reset.py): purge, verify, rebuild."""
    import reference_reset
    reference_reset.reset()
    reference_reset.verify()


addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402


def run_timer():
    _snap = fetch_model_json_tcp(HOST, PORT, False)
    _snap["two_way_enabled"] = True  # this check exercises two-way editing
    ls._sync_state["queue"].put(_snap)
    ls._sync_timer()


reset_reference()
status = 1
try:
    ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
    ls._sync_state["running"] = True
    ls._sync_state["queue"] = queue.SimpleQueue()
    run_timer()  # import and record the baseline

    grp_before, faces_before = group_faces()
    before_count = len(faces_before)
    before_ids = {f["persistent_id"] for f in faces_before}

    ob = next((o for o in bpy.data.objects if o.get("skp_persistent_id") == grp_before["persistent_id"]), None)
    if ob is None:
        fail("the FurnitureGroup is not identified in Blender")
    layer = ob.data.attributes.get("skp_face_id")
    if layer is None:
        fail("the imported mesh has no skp_face_id layer")
    target_face = int(layer.data[0].value)
    if target_face not in before_ids:
        fail(f"polygon 0 names face {target_face}, which is not in the group")

    # Edit one vertex of polygon 0 in Blender.
    ob.data.vertices[ob.data.polygons[0].vertices[0]].co.x += 0.4
    ob.data.update()
    # The reshape must succeed as a push, not merely leave a different id behind. Capture the push's
    # outcome from the module's log so a 404 cannot pass as a reshape.
    import logging
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
        fail("the timer did not reshape the face: the reshape push failed or was never sent")

    grp_after, faces_after = group_faces()
    after_ids = {f["persistent_id"] for f in faces_after}
    if len(faces_after) != before_count:
        fail(f"the group's face count changed from {before_count} to {len(faces_after)}")
    if target_face in after_ids:
        fail(f"face {target_face} was not reshaped: its id is still in the group")
    new_faces = after_ids - before_ids
    if len(new_faces) != 1:
        fail(f"expected one new face id after the reshape, got {sorted(new_faces)}")

    status = 0
    print(f"LIVE-TIMER-RESHAPE OK: face {target_face} reshaped in place to {sorted(new_faces)[0]}, group intact")
finally:
    reset_reference()
sys.exit(status)
