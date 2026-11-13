"""
Live timer imported-geometry check (gap 5 boundary). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_timer_imported_edit_check.py

A vertex edit on an object imported from SketchUp cannot round-trip: the face is part of a group or
component, and a per-vertex replace would destroy its identity and context. The transform of the same
object does round-trip (milestone 1). This check asserts the boundary is explicit: the vertex edit is
NOT pushed, SketchUp is left as it was, and the user is warned that the edit was kept in Blender only.
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

    before = {e.get("persistent_id"): e.get("vertices") for e in model()["entities"] if e.get("type") == "Face"}

    # Move a vertex of an object imported from SketchUp (it carries its SketchUp id and import marker).
    imported = next((o for o in bpy.data.objects if o.get("skp_persistent_id") and o.get("skp_link_import")
                     and o.type == "MESH" and o.name.startswith("G-")), None)
    if imported is None:
        fail("no imported mesh found to edit")
    imported_name = imported.name
    imported.data.vertices[0].co.x += 0.5
    imported.data.update()
    run_timer()

    after = {e.get("persistent_id"): e.get("vertices") for e in model()["entities"] if e.get("type") == "Face"}
    if after != before:
        fail("a vertex edit on imported geometry changed SketchUp; it must stay in Blender only")
    warned = [w for w in sync_push.warnings() if "imported" in w.lower() or "kept in blender" in w.lower()]
    if not warned:
        fail("the vertex edit on imported geometry was dropped without a warning")
    status = 0
    print(f"LIVE-TIMER-IMPORTED OK: vertex edit on {imported_name} kept in Blender and reported")
finally:
    reset_reference()
sys.exit(status)
