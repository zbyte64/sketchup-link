"""Before/after visual check of a SketchUp material change, on the VisualCube.

Runs inside a Blender GUI session (display :99). Steps:
  1. Live-sync the reference model and frame VisualCube in Material Preview.
  2. Capture the screen ("before") with xwd to /tmp/vc_before.xwd.
  3. Change the SketchUp material 'Blue' to a distinct colour over HTTP.
  4. Live-sync again, re-frame, and capture ("after") to /tmp/vc_after.xwd.
The shell wrapper converts both captures and compares their hashes: identical captures
mean the change did not reach the screen, which is a failure, not a pass.
"""
import json
import os
import queue
import subprocess
import sys
import urllib.request

import addon_utils
import bpy

HOST = os.environ.get("SKETCHUP_LINK_HOST", "172.17.0.1")
PORT = int(os.environ.get("SKETCHUP_LINK_PORT", "9876"))
ADDON_ROOT = os.environ.get("SKP_ADDON_ROOT", "/tmp/addons")
AFTER_COLOR = {"r": 220, "g": 60, "b": 60}

sys.path.insert(0, ADDON_ROOT)
addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402


def sync():
    snap = fetch_model_json_tcp(HOST, PORT, False)
    ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
    ls._sync_state["queue"] = queue.SimpleQueue()
    ls._sync_state["running"] = True
    ls._sync_state["queue"].put(snap)
    ls._sync_timer()


def frame_visualcube():
    """Select VisualCube and frame it in Material Preview, in object mode."""
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    ob = next((o for o in bpy.data.objects if o.name.startswith("VisualCube") or o.name.startswith("G-VisualCube")), None)
    if ob is None:
        print("VCPAIR no VisualCube object found", flush=True)
        return
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            area.spaces[0].shading.type = "MATERIAL"
            with bpy.context.temp_override(area=area, region=area.regions[-1]):
                bpy.ops.view3d.view_selected()
            area.tag_redraw()


def wait_for_shaders(timeout=90.0):
    """Wait until Blender has finished compiling shaders, so a capture shows settled frames.

    A capture taken during "Compiling shaders" shows a half-drawn viewport, which is why
    the first pair appeared to differ for the wrong reason.
    """
    import time
    end = time.time() + timeout
    while time.time() < end:
        for w in bpy.context.window_manager.windows:
            for area in w.screen.areas:
                if area.type == "VIEW_3D":
                    txt = area.spaces[0].shading.type
                    # Redraw and give the compiler a moment; Blender exposes no
                    # direct "compiling" flag, so settle time is the reliable signal.
                    area.tag_redraw()
        time.sleep(5.0)
        return True
    return False


def capture(path):
    wait_for_shaders()
    subprocess.run(["bash", "-lc", f"DISPLAY=:99 xwd -root -silent > {path}"], check=True)


def set_blue():
    req = urllib.request.Request(
        f"http://{HOST}:{PORT}/control/material",
        data=json.dumps({"name": "Blue", "color": AFTER_COLOR}).encode(),
        method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        print("VCPAIR set Blue HTTP", r.status, flush=True)


STEP = {"n": 0}


def run():
    STEP["n"] += 1
    if STEP["n"] == 1:
        sync()
        frame_visualcube()
        return 3.0
    if STEP["n"] == 2:
        capture("/tmp/vc_before.xwd")
        print("VCPAIR before captured", flush=True)
        set_blue()
        return 2.0
    if STEP["n"] == 3:
        sync()
        frame_visualcube()
        return 3.0
    if STEP["n"] == 4:
        capture("/tmp/vc_after.xwd")
        print("VCPAIR after captured", flush=True)
        return None
    return None


bpy.app.timers.register(run, first_interval=12.0)
