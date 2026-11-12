"""
Live timer overlap check (milestone 2, gap 5). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_timer_overlap_check.py

Two user triangles share one location band: they overlap in x and y, offset only in z. The face check
in live_timer_modify_check keys faces by location band, so this case is where it would confuse them.
The test pushes both, edits one, and asserts that exactly the edited object's face is replaced and
the other keeps its own id. Objects are tracked by their stored SketchUp id, never by position.
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
    print(f"LIVE-TIMER-OVERLAP FAIL: {msg}")
    sys.exit(1)


def post(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body or {}).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def face_ids():
    """Ids of all top-level faces in SketchUp."""
    d = json.loads(urllib.request.urlopen(BASE + "/model", timeout=30).read())
    return {e["persistent_id"] for e in d["entities"] if e.get("type") == "Face"}


def reset_reference():
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


def make_triangle(name, z, pts):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(x, y, z) for x, y in pts], [], [(0, 1, 2)])
    mesh.update()
    ob = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(ob)
    return ob


reset_reference()
status = 1
try:
    ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
    ls._sync_state["running"] = True
    ls._sync_state["queue"] = queue.SimpleQueue()
    run_timer()

    # Same x/y footprint, different z: they share one location band.
    a = make_triangle("OverlapA", 0.0, [(0.3, 0.3), (0.6, 0.3), (0.3, 0.6)])
    b = make_triangle("OverlapB", 0.5, [(0.3, 0.3), (0.6, 0.3), (0.3, 0.6)])
    run_timer()
    before = face_ids() - set()
    pid_a = int(a["skp_persistent_id"]) if "skp_persistent_id" in a else None
    pid_b = int(b["skp_persistent_id"]) if "skp_persistent_id" in b else None
    if pid_a is None or pid_b is None or pid_a == pid_b:
        fail(f"both overlapping triangles must be pushed with distinct ids (a={pid_a}, b={pid_b})")
    if not {pid_a, pid_b} <= before:
        fail("the pushed ids are not faces in SketchUp")

    # Edit only A. B must keep its own face; only A's face may be replaced.
    a.data.vertices[2].co.y = 0.8
    a.data.update()
    run_timer()

    after = face_ids()
    if pid_b not in after:
        fail(f"the unedited object's face {pid_b} was removed; the edit to A must not touch B")
    if pid_a in after:
        fail(f"A's old face {pid_a} was not replaced after its vertex edit")
    new_a = int(a["skp_persistent_id"])
    if new_a not in after:
        fail(f"A's new id {new_a} is not a face in SketchUp")
    if len(after - before) != 1 or len(before - after) != 1:
        fail(f"expected one face replaced, got +{len(after - before)} / -{len(before - after)}")

    status = 0
    print(f"LIVE-TIMER-OVERLAP OK: A replaced ({pid_a} -> {new_a}), B kept {pid_b}")
finally:
    reset_reference()
sys.exit(status)
