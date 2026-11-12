"""
Live Blender -> SketchUp delete round trip (milestone 2). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_sync_delete_push_check.py

Imports the live snapshot, deletes a tagged Blender object, detects the removal, and asserts the
SketchUp entity is erased through the delete route. The reference model is restored afterwards.
Objects are found by stored SketchUp id, never by name.
"""

import json
import os
import re
import queue
import sys
import urllib.error
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
    print(f"LIVE-DELETE-PUSH FAIL: {msg}")
    sys.exit(1)


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def get_model():
    with urllib.request.urlopen(BASE + "/model", timeout=30) as r:
        return json.loads(r.read())


addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import edit_capture as ec  # noqa: E402
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402

snap = fetch_model_json_tcp(HOST, PORT, False)
ls._sync_state["queue"] = queue.SimpleQueue()
ls._sync_state["running"] = True
ls._sync_state["queue"].put(snap)
ls._sync_timer()

# Delete the tagged group. Its SketchUp id is the identity; the name is not used.
group = next((o for o in bpy.data.objects if o.get("skp_persistent_id") and o.name.startswith("G-")), None)
if group is None:
    fail("could not find the imported group by its SketchUp id")
pid = int(group["skp_persistent_id"])

ec.record_import_state()
tracked = set(ec.tracker()._synced.keys())
bpy.data.objects.remove(group, do_unlink=True)

present = {int(o["skp_persistent_id"]) for o in bpy.data.objects if "skp_persistent_id" in o}
gone = ec.removed_ids(tracked, present)
if pid not in gone:
    fail(f"deleting {pid} in Blender was not detected as a removal (removed={gone})")

# Push the removal. SketchUp-wins: only erase if SketchUp still has the entity as it was.
status = post("/control/geometry/delete", {"persistent_id": pid})
if status != 200:
    fail(f"delete route returned HTTP {status}")
names_after = [e.get("persistent_id") for e in get_model().get("entities", [])]
if pid in names_after:
    fail(f"SketchUp still has entity {pid} after the delete push")

# Restore the reference model with the full reset the e2e fixture uses: purge over the MCP tunnel
# (erases entities, definitions, materials and pages), then rebuild. A bare rebuild stacks duplicates.
import socket  # noqa: E402

src = open(os.path.join(REPO, "tests", "bdd", "conftest.py"), encoding="utf-8").read()
purge = re.search(r'_PURGE_ALL = \((.*?)\n\)', src, re.S).group(1)
purge_code = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', purge))
mcp = socket.create_connection(("127.0.0.1", int(os.environ.get("MCP_LOCAL_PORT", "9878"))), timeout=60)
mcp.sendall((json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": "eval_ruby", "arguments": {"code": purge_code}}}) + "\n").encode())
reply = mcp.recv(65536).decode()
mcp.close()
if '"0,0,0,0"' not in reply:
    fail(f"reference reset incomplete after the delete check: {reply[-160:]}")
if post("/test_model", None) != 200:
    fail("could not rebuild the reference model after the delete check")

print(f"LIVE-DELETE-PUSH OK: Blender delete of {pid} was detected and erased in SketchUp")
sys.exit(0)
