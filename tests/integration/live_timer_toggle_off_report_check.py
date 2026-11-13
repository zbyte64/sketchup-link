"""
Live toggle-off reporting check. Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_timer_toggle_off_report_check.py

With two-way editing off (the shipped default), a Blender edit must NOT reach SketchUp but MUST be reported:
the user should see a warning saying the edit was not sent because two-way editing is off. Before this check,
the gate dropped edits silently and the next import overwrote them. The reference model is restored after.
"""
import json
import os
import queue
import sys
import urllib.request

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
    print(f"LIVE-TOGGLE-OFF-REPORT FAIL: {msg}")
    sys.exit(1)


addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin import sync_push as sp  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402


def run_timer():
    ls._sync_state["queue"].put(fetch_model_json_tcp(HOST, PORT, False))
    ls._sync_timer()


reference_reset.reset()
reference_reset.verify()
status = 1
try:
    ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
    ls._sync_state["running"] = True
    ls._sync_state["queue"] = queue.SimpleQueue()
    run_timer()  # import + baseline; the live snapshot says two_way_enabled false

    ob = next((o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("G-VisualCube")), None)
    if ob is None:
        fail("no imported G-VisualCube to edit")
    me = ob.data
    layer = me.attributes.get("skp_face_id")
    if layer is None:
        fail("imported object has no skp_face_id layer")
    polys = [p for p in me.polygons if int(layer.data[p.index].value) != 0]
    if not polys:
        fail("no face polygons to edit")
    vi = polys[0].vertices[0]
    me.vertices[vi].co.x += 0.03
    me.update()
    bpy.context.view_layer.update()

    run_timer()  # the toggle is off: the edit must be reported, not written

    warns = list(sp.warnings())
    if not any("two-way editing is off" in w for w in warns):
        fail(f"the dropped edit was not reported; warnings are {warns}")

    d = json.loads(urllib.request.urlopen(f"http://{HOST}:{PORT}/model", timeout=30).read())
    print(f"LIVE-TOGGLE-OFF-REPORT OK: dropped edit reported; warnings={warns[-1][:80]}")
    status = 0
finally:
    reference_reset.reset()
    reference_reset.verify()
sys.exit(status)
