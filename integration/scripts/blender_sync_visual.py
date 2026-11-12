"""Live-sync visual check for a Blender debug container (run inside the GUI session).

Starts the SketchUp Link add-on, performs one live import from the SketchUp server, and
prints the imported object names as SYNCVIS lines. Screenshot the GUI display afterwards
(xwd + convert on the container's :99) to inspect the result.

Configure the SketchUp host with SKETCHUP_LINK_HOST (default: the Docker bridge gateway,
which is how a debug container reaches the host; 127.0.0.1 is the container itself).
"""
import os
import queue
import sys

import addon_utils
import bpy

ADDON_ROOT = os.environ.get("SKP_ADDON_ROOT", "/tmp/addons")
HOST = os.environ.get("SKETCHUP_LINK_HOST", "172.17.0.1")
PORT = int(os.environ.get("SKETCHUP_LINK_PORT", "9876"))

sys.path.insert(0, ADDON_ROOT)
addon_utils.enable("blender_plugin", default_set=True, persistent=False)

from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402

snap = fetch_model_json_tcp(HOST, PORT, False)
ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
ls._sync_state["queue"] = queue.SimpleQueue()
ls._sync_state["running"] = True
ls._sync_state["queue"].put(snap)
ls._sync_timer()
print("SYNCVIS objects:", sorted(o.name for o in bpy.data.objects), flush=True)
