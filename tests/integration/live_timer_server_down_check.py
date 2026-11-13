"""
Live server-down reporting check. Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_timer_server_down_check.py

If SketchUp stops answering, snapshots silently stop and the panel still says "running" with a stale model.
The poll loop must tell the user. This check starts sync pointed at a dead port, waits past three poll
failures, and requires a warning that SketchUp stopped responding. No SketchUp changes are made.
"""
import os
import queue
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
for p in (REPO, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import addon_utils  # noqa: E402
import bpy  # noqa: E402


def fail(msg):
    print(f"LIVE-SERVER-DOWN FAIL: {msg}")
    sys.exit(1)


addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin import sync_push as sp  # noqa: E402

import threading  # noqa: E402

# Point the poll thread at a port nothing listens on; short interval so three failures pass quickly.
ls._sync_state["conn_config"] = {"mode": "TCP", "host": "127.0.0.1", "port": 9, "binary_textures": False}
ls._sync_state["running"] = True
ls._sync_state["queue"] = queue.SimpleQueue()
stop_event = threading.Event()
t = threading.Thread(target=ls._poll_loop, args=(stop_event, ls._sync_state["queue"],
                                                 ls._sync_state["conn_config"], 0.5), daemon=True)
t.start()
deadline = time.monotonic() + 20
warned = False
while time.monotonic() < deadline:
    if any("stopped responding" in w for w in sp.warnings()):
        warned = True
        break
    time.sleep(0.5)
stop_event.set()

if not warned:
    fail(f"the dead server was not reported; warnings are {list(sp.warnings())}")
print(f"LIVE-SERVER-DOWN OK: dead server reported; warnings={[w for w in sp.warnings() if 'stopped' in w][0][:80]}")
sys.exit(0)
