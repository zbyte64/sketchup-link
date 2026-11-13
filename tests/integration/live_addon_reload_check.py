"""
Live addon reload check (gap: nothing covered disable and re-enable). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_addon_reload_check.py

The depsgraph edit handler is registered in register() and must be removed in unregister(). Across a disable and a
re-enable it must be present exactly once: a missing removal leaves a stale handler; a missing guard stacks duplicates,
so every Blender edit would be queued twice. This check asserts the count after each step.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import addon_utils  # noqa: E402
import bpy  # noqa: E402


def count_handler():
    return sum(1 for h in bpy.app.handlers.depsgraph_update_post if getattr(h, "__name__", "") == "_edit_capture_handler")


def fail(msg):
    print(f"LIVE-ADDON-RELOAD FAIL: {msg}")
    sys.exit(1)


addon_utils.enable("blender_plugin", default_set=True, persistent=False)
after_enable = count_handler()
if after_enable != 1:
    fail(f"after enable the handler count is {after_enable}, expected 1")

addon_utils.disable("blender_plugin", default_set=True)
after_disable = count_handler()
if after_disable != 0:
    fail(f"after disable the handler count is {after_disable}, expected 0 (stale handler left behind)")

addon_utils.enable("blender_plugin", default_set=True, persistent=False)
after_reenable = count_handler()
if after_reenable != 1:
    fail(f"after re-enable the handler count is {after_reenable}, expected 1 (duplicate or missing)")

print(f"LIVE-ADDON-RELOAD OK: handler count 1 -> 0 -> 1 across disable and re-enable")
sys.exit(0)
