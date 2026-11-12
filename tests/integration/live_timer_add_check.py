"""
Live timer add check (milestone 2). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_timer_add_check.py

Creates a triangle mesh in Blender, runs the real live timer, and asserts:
  1. a SketchUp face now exists for it (the timer pushed the add);
  2. the Blender object is tagged with the id SketchUp returned (identity write-back);
  3. a second timer run does not create another face (echo suppression).
The reference model is restored with the full purge before and after every run.
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

import addon_utils  # noqa: E402
import bpy  # noqa: E402

HOST = os.environ.get("SKETCHUP_LINK_HOST", "127.0.0.1")
PORT = int(os.environ.get("SKETCHUP_LINK_PORT", "9876"))
BASE = f"http://{HOST}:{PORT}"


def fail(msg):
    print(f"LIVE-TIMER-ADD FAIL: {msg}")
    sys.exit(1)


def post(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body or {}).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def model():
    return json.loads(urllib.request.urlopen(BASE + "/model", timeout=30).read())


def face_count():
    """Faces at the top level of the SketchUp model."""
    return sum(1 for e in model()["entities"] if e.get("type") == "Face")


def reset_reference():
    """Full purge over the MCP tunnel, then rebuild. The only reset that leaves the model clean."""
    src = open(os.path.join(REPO, "tests", "bdd", "conftest.py"), encoding="utf-8").read()
    purge = re.search(r'_PURGE_ALL = \((.*?)\n\)', src, re.S).group(1)
    code = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', purge))
    mcp = socket.create_connection(("127.0.0.1", int(os.environ.get("MCP_LOCAL_PORT", "9878"))), timeout=60)
    mcp.sendall((json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": "eval_ruby", "arguments": {"code": code}}}) + "\n").encode())
    reply = mcp.recv(65536).decode()
    mcp.close()
    if '"0,0,0,0"' not in reply:
        raise RuntimeError(f"reference reset incomplete: {reply[-160:]}")
    post("/test_model")


addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402


def run_timer():
    ls._sync_state["queue"].put(fetch_model_json_tcp(HOST, PORT, False))
    ls._sync_timer()


reset_reference()
try:
    ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
    ls._sync_state["running"] = True
    ls._sync_state["queue"] = queue.SimpleQueue()
    run_timer()  # establish the baseline from the reference model

    faces_before = face_count()

    # Draw a triangle in Blender: a mesh object tagged with no identity, as a user would create it.
    mesh = bpy.data.meshes.new("UserTriangle")
    mesh.from_pydata([(0.3, 0.3, 0.0), (0.6, 0.3, 0.0), (0.3, 0.6, 0.0)], [], [(0, 1, 2)])
    mesh.update()
    ob = bpy.data.objects.new("UserTriangle", mesh)
    bpy.context.collection.objects.link(ob)

    run_timer()  # the timer should push the add

    faces_after = face_count()
    if faces_after != faces_before + 1:
        fail(f"expected one new SketchUp face, faces went {faces_before} -> {faces_after}")

    if "skp_persistent_id" not in ob:
        fail("the Blender object was not given the SketchUp id returned by the add")
    new_pid = int(ob["skp_persistent_id"])
    ids = {e.get("persistent_id") for e in model()["entities"]}
    if new_pid not in ids:
        fail(f"the id written back ({new_pid}) is not a face in SketchUp")

    run_timer()  # echo suppression: the same polygon must not be pushed again
    if face_count() != faces_after:
        fail(f"a second sync created another face ({face_count()}); the add was echoed")

    print(f"LIVE-TIMER-ADD OK: face {new_pid} created, id written back, not echoed")
    status = 0
except SystemExit:
    raise
finally:
    reset_reference()

sys.exit(status)
