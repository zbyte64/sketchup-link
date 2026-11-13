"""
Live import-failure reporting check. Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_timer_import_fail_report_check.py

Repeated import failures used to only log and back off: the user kept looking at a stale model with no
notice. This check makes SceneImporter.load raise for several timer passes and requires a warning that
imports keep failing, then restores load and requires the recovery notice. The reference model is restored
after.
"""
import os
import queue
import sys

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
    print(f"LIVE-IMPORT-FAIL-REPORT FAIL: {msg}")
    sys.exit(1)


addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin import sync_push as sp  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402
from blender_plugin.scene_importer import SceneImporter  # noqa: E402

reference_reset.reset()
reference_reset.verify()
status = 1
try:
    ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
    ls._sync_state["running"] = True
    ls._sync_state["queue"] = queue.SimpleQueue()
    ls._sync_state["queue"].put(fetch_model_json_tcp(HOST, PORT, False))
    ls._sync_timer()  # a good import first, so the baseline exists

    orig = SceneImporter.load

    def boom(self, *a, **k):
        raise RuntimeError("forced import failure (check)")

    SceneImporter.load = boom
    for _ in range(4):
        ls._sync_state["queue"].put(fetch_model_json_tcp(HOST, PORT, False))
        ls._sync_timer()
    SceneImporter.load = orig

    warns = list(sp.warnings())
    if not any("keep failing" in w for w in warns):
        fail(f"repeated import failures were not reported; warnings are {warns}")

    ls._sync_state["queue"].put(fetch_model_json_tcp(HOST, PORT, False))
    ls._sync_timer()
    warns = list(sp.warnings())
    if not any("recovered" in w for w in warns):
        fail(f"the recovery was not reported; warnings are {warns}")

    status = 0
    print(f"LIVE-IMPORT-FAIL-REPORT OK: repeated failures reported once, recovery reported "
          f"(failures={ls._sync_state.get('failures')})")
finally:
    reference_reset.reset()
    reference_reset.verify()
sys.exit(status)
