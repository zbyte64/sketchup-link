"""
Live timer conflict check (gap 6). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_timer_conflict_check.py

Changes the same object on both sides between two polls: the FurnitureGroup is moved in SketchUp, and its
imported counterpart is moved in Blender too. Under the SketchUp-wins policy the live timer must keep
SketchUp's value, drop the Blender edit, and record a warning that names the object. The reference model is
restored with the full purge before and after.
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
MCP_PORT = int(os.environ.get("MCP_LOCAL_PORT", "9878"))


def fail(msg):
    print(f"LIVE-TIMER-CONFLICT FAIL: {msg}")
    sys.exit(1)


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def model():
    return json.loads(urllib.request.urlopen(BASE + "/model", timeout=30).read())


def group_x(pid):
    e = next(x for x in model()["entities"] if x.get("persistent_id") == pid)
    return e["transformation"][3]


def reset_reference():
    """The shared reset (tests/integration/reference_reset.py): purge, verify, rebuild."""
    import reference_reset
    reference_reset.reset()
    reference_reset.verify()


addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin import sync_push  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402


def run_timer():
    ls._sync_state["queue"].put(fetch_model_json_tcp(HOST, PORT, False))
    ls._sync_timer()


reset_reference()
status = 1
try:
    ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
    ls._sync_state["running"] = True
    ls._sync_state["queue"] = queue.SimpleQueue()
    run_timer()  # import and record the baseline
    sync_push._warnings.clear()

    grp = next(e for e in model()["entities"] if e.get("type") == "Group" and e.get("name") == "FurnitureGroup")
    pid = grp["persistent_id"]
    ob = next((o for o in bpy.data.objects if o.get("skp_persistent_id") == pid), None)
    if ob is None:
        fail("the FurnitureGroup is not identified in Blender")
    # The baseline is keyed by the imported object's stored identity. Record it explicitly after the import,
    # so the Blender move below is a tracked transform edit and not an untracked change.
    from blender_plugin import edit_capture as _ec
    _ec.record_import_state()

    # Both sides change the same object between polls. SketchUp moves to x = 0.5 m; Blender moves to x = 0.9 m.
    post("/control/geometry/transform", {"persistent_id": pid,
                                         "transformation": [1, 0, 0, 0.5, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]})
    ob.location.x += 0.9
    # Blender runs the depsgraph handler on every update; it is what captures the move as an edit.
    _ec.on_depsgraph_update(bpy.context.scene)
    run_timer()

    sk_x = group_x(pid)
    if abs(sk_x - 0.5) > 1e-3:
        fail(f"SketchUp's value did not stand: x is {sk_x}, expected the SketchUp value 0.5")
    warned = [w for w in sync_push.warnings() if str(pid) in w or "FurnitureGroup" in w or "G-" in w]
    if not warned:
        fail(f"the conflict was not reported: warnings are {sync_push.warnings()}")

    status = 0
    print(f"LIVE-TIMER-CONFLICT OK: SketchUp's value stood (x={sk_x}) and the conflict was reported")
finally:
    reset_reference()
sys.exit(status)
