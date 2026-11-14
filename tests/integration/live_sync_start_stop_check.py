"""
Live start/stop operator check (the real panel-button path). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_sync_start_stop_check.py

Every other check drives _sync_state and _sync_timer directly; none exercises the operators a user clicks.
This one sets the connection preferences, calls skp_start_live_sync, and requires: the conn_config honors
the preferences (TCP host/port), the poll thread delivers a snapshot, one timer pass imports it, and
skp_stop_live_sync stops cleanly. The reference model is restored after.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
for p in (REPO, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import addon_utils  # noqa: E402
import bpy  # noqa: E402
import reference_reset  # noqa: E402

HOST = os.environ.get("SKETCHUP_LINK_HOST", "127.0.0.1")
PORT = int(os.environ.get("SKETCHUP_LINK_PORT", "9876"))


def fail(msg):
    print(f"LIVE-START-STOP FAIL: {msg}")
    sys.exit(1)


addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls  # noqa: E402

reference_reset.reset()
reference_reset.verify()
status = 1
try:
    prefs = bpy.context.preferences.addons["blender_plugin"].preferences
    prefs.connection_mode = "TCP"
    # "localhost" resolves the same as the default "127.0.0.1" but is NOT equal to it, so the assertion below
    # proves the preference is actually read (a hardcoded default would pass with HOST itself).
    prefs.tcp_host = "localhost"
    prefs.tcp_port = PORT

    res = bpy.ops.import_scene.skp_start_live_sync()
    if res != {"FINISHED"}:
        fail(f"start operator returned {res}")
    state = ls._sync_state
    if not state["running"]:
        fail("state not running after start operator")
    cc = state["conn_config"]
    if cc["mode"] != "TCP" or cc["host"] != "localhost" or cc["port"] != PORT:
        fail(f"conn_config did not honor preferences: {cc}")

    # The poll thread is real; wait for it to deliver a snapshot.
    deadline = time.monotonic() + 15
    while state["queue"].empty() and time.monotonic() < deadline:
        time.sleep(0.5)
    if state["queue"].empty():
        fail("poll thread never delivered a snapshot")

    ls._sync_timer()  # one manual pass (background does not tick app timers)
    imported = [o for o in bpy.data.objects if "skp_persistent_id" in o]
    if not imported:
        fail("timer pass imported no tagged objects")

    res = bpy.ops.import_scene.skp_stop_live_sync()
    if res != {"FINISHED"}:
        fail(f"stop operator returned {res}")
    if state["running"]:
        fail("still running after stop operator")
    if state["stop_event"] is not None and not state["stop_event"].is_set():
        fail("stop_event not set")

    status = 0
    print(f"LIVE-START-STOP OK: prefs honored ({cc['host']}:{cc['port']}), poll delivered, "
          f"{len(imported)} objects imported, clean stop")
finally:
    reference_reset.reset()
    reference_reset.verify()
sys.exit(status)
