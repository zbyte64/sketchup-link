"""
Live timer modify check (milestone 2, gap 5). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_timer_modify_check.py

Draws a triangle, lets the timer push it as a face, then moves one vertex in Blender and runs the
timer again. Per the design, an edit of an existing user mesh is delete-and-re-add: the old SketchUp
face must be removed and exactly one new face must replace it. Two faces would mean the old one was
left behind; zero would mean the edit was lost. The reference model is restored before and after.
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
    print(f"LIVE-TIMER-MODIFY FAIL: {msg}")
    sys.exit(1)


def post(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body or {}).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def model():
    return json.loads(urllib.request.urlopen(BASE + "/model", timeout=30).read())


def user_faces():
    """Top-level faces at the user triangle's location (x around 0.3-0.6 m)."""
    out = []
    for e in model()["entities"]:
        if e.get("type") == "Face":
            xs = [v[0] for v in e.get("vertices", [])]
            if xs and min(xs) > 0.2 and max(xs) < 0.9:
                out.append(e.get("persistent_id"))
    return out


def reset_reference():
    """The shared reset (tests/integration/reference_reset.py): purge, verify, rebuild."""
    import reference_reset
    reference_reset.reset()
    reference_reset.verify()


addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls  # noqa: E402
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
    run_timer()

    mesh = bpy.data.meshes.new("UserTriangle")
    mesh.from_pydata([(0.3, 0.3, 0.0), (0.6, 0.3, 0.0), (0.3, 0.6, 0.0)], [], [(0, 1, 2)])
    mesh.update()
    ob = bpy.data.objects.new("UserTriangle", mesh)
    bpy.context.collection.objects.link(ob)
    run_timer()
    before = user_faces()
    if len(before) != 1:
        fail(f"expected one face after the add, found {len(before)}: {before}")

    # Move one vertex in Blender. This is the modification the design models as delete-and-re-add.
    mesh.vertices[2].co.y = 0.8
    mesh.update()
    run_timer()

    after = user_faces()
    if len(after) != 1:
        fail(f"after the vertex edit there are {len(after)} faces {after}; expected exactly one "
             f"(the old face must be removed and replaced)")
    if after == before:
        fail("the face is unchanged after the vertex edit; the edit was not pushed")
    status = 0
    print(f"LIVE-TIMER-MODIFY OK: vertex edit replaced face {before[0]} with {after[0]}")
finally:
    reset_reference()
sys.exit(status)
