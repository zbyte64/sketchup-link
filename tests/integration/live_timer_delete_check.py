"""
Live timer delete check (milestone 2). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_timer_delete_check.py

Unlike live_sync_delete_push_check (which drives the push directly), this runs the real live
timer, _sync_timer, after deleting a tagged object in Blender. The timer must detect the removal,
erase the SketchUp entity through the delete route, and then import the snapshot. Objects are found
by stored SketchUp id. The reference model is restored with the full reset afterwards.
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
    print(f"LIVE-TIMER-DELETE FAIL: {msg}")
    sys.exit(1)


def post(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body or {}).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status



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
    post("/test_model", None)

addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import edit_capture as ec  # noqa: E402
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402

reset_reference()
try:
    ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
    ls._sync_state["running"] = True
    ls._sync_state["queue"] = queue.SimpleQueue()
    ls._sync_state["queue"].put(fetch_model_json_tcp(HOST, PORT, False))
    ls._sync_timer()

    group = next((o for o in bpy.data.objects if o.get("skp_persistent_id") and o.name.startswith("G-")), None)
    if group is None:
        fail("could not find the imported group by its SketchUp id")
    pid = int(group["skp_persistent_id"])

    ec.record_import_state()
    bpy.data.objects.remove(group, do_unlink=True)

    # Run the real timer: it pushes the removal, then imports the snapshot.
    ls._sync_state["queue"].put(fetch_model_json_tcp(HOST, PORT, False))
    ls._sync_timer()

    names = {e.get("persistent_id") for e in json.loads(urllib.request.urlopen(BASE + "/model", timeout=30).read())["entities"]}
    if pid in names:
        fail(f"the live timer did not erase SketchUp entity {pid}")
    if pid in ec.tracker()._synced:
        fail(f"the timer did not forget the erased id {pid}")

    # Restore with the same full purge the e2e fixture runs over the MCP tunnel, then rebuild.
    src = open(os.path.join(REPO, "tests", "bdd", "conftest.py"), encoding="utf-8").read()
    purge = re.search(r'_PURGE_ALL = \((.*?)\n\)', src, re.S).group(1)
    purge_code = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', purge))
    mcp = socket.create_connection(("127.0.0.1", int(os.environ.get("MCP_LOCAL_PORT", "9878"))), timeout=60)
    mcp.sendall((json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": "eval_ruby", "arguments": {"code": purge_code}}}) + "\n").encode())
    reply = mcp.recv(65536).decode()
    mcp.close()
    if '"0,0,0,0"' not in reply:
        fail(f"reference reset incomplete: {reply[-160:]}")
    post("/test_model", None)

except SystemExit:
    raise
finally:
    reset_reference()
print(f"LIVE-TIMER-DELETE OK: the live timer erased SketchUp entity {pid} and forgot it")
sys.exit(0)
