"""
Live timer imported-geometry check (gap 5 boundary). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_timer_imported_edit_check.py

A vertex edit on an object imported from SketchUp is pushed to SketchUp by reshaping the face in place
(geometry/face/reshape), keeping its owning group. This check asserts that contract: the edit changes the
SketchUp face, the group keeps its face count, and no "kept in Blender only" warning is raised. It replaces
an earlier check that asserted the opposite, written before the reshape route existed.
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
    print(f"LIVE-TIMER-IMPORTED FAIL: {msg}")
    sys.exit(1)


def post(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body or {}).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def model():
    return json.loads(urllib.request.urlopen(BASE + "/model", timeout=30).read())


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
    run_timer()
    sync_push._warnings.clear()

    def group_faces_now():
        grp = next(e for e in model()["entities"] if e.get("type") == "Group" and e.get("name") == "FurnitureGroup")
        return {f["persistent_id"]: f.get("vertices") for f in grp["entities"] if f.get("type") == "Face"}

    before = group_faces_now()

    # Move a vertex of an object imported from SketchUp (it carries its SketchUp id and import marker).
    # Select the FurnitureGroup by its SketchUp id, the object whose faces the check compares. Selecting by
    # name prefix picked G-VisualCube, so the check edited an object SketchUp's group did not contain.
    group_json = next(e for e in model()["entities"] if e.get("type") == "Group" and e.get("name") == "FurnitureGroup")
    imported = next((o for o in bpy.data.objects if o.get("skp_persistent_id") == group_json["persistent_id"]), None)
    if imported is None:
        fail("no imported mesh found to edit")
    imported_name = imported.name
    imported.data.vertices[imported.data.polygons[0].vertices[0]].co.x += 0.4
    imported.data.update()
    run_timer()

    after = group_faces_now()
    if after == before:
        fail("the vertex edit on imported geometry was not pushed: SketchUp's faces are unchanged")
    if len(after) != len(before):
        fail(f"the group's face count changed from {len(before)} to {len(after)}")
    if set(after) == set(before):
        fail("the group's faces kept their ids; a reshape must give the face a new id")
    kept = [w for w in sync_push.warnings() if "kept in blender" in w.lower()]
    if kept:
        fail(f"the edit was pushed, yet still reported as kept in Blender: {kept}")
    status = 0
    print(f"LIVE-TIMER-IMPORTED OK: vertex edit on {imported_name} pushed to SketchUp by reshape")
finally:
    reset_reference()
sys.exit(status)
