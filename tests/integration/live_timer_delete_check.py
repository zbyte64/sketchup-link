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

sys.path.insert(0, HERE)
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
    """The shared reset (tests/integration/reference_reset.py): purge, verify, rebuild."""
    import reference_reset
    reference_reset.reset()
    reference_reset.verify()

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

    # Baseline from the live snapshot, as the production timer does: only ids SketchUp still reports are enrolled.
    ec.record_import_state(live_ids=ls._snapshot_entity_ids(fetch_model_json_tcp(HOST, PORT, False)))
    bpy.data.objects.remove(group, do_unlink=True)

    # Run the real timer: it pushes the removal, then imports the snapshot.
    ls._sync_state["queue"].put(fetch_model_json_tcp(HOST, PORT, False))
    ls._sync_timer()

    names = {e.get("persistent_id") for e in json.loads(urllib.request.urlopen(BASE + "/model", timeout=30).read())["entities"]}
    if pid in names:
        fail(f"the live timer did not erase SketchUp entity {pid}")
    if pid in ec.tracker()._synced:
        fail(f"the timer did not forget the erased id {pid}")

    # Restore through the shared reset (purge, verify, rebuild).
    import reference_reset
    reference_reset.reset()
    reference_reset.verify()

except SystemExit:
    raise
finally:
    reset_reference()
print(f"LIVE-TIMER-DELETE OK: the live timer erased SketchUp entity {pid} and forgot it")
sys.exit(0)
