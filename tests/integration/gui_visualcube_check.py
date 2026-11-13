"""
GUI visual check: a SketchUp material change reaches the screen. Runs in the Blender GUI, on the virtual display
the debug image's entrypoint starts, in a throwaway container (the runner launches it; no long-lived container):

    docker run --rm --network host -e DISPLAY=:120 -v "$PWD":/plugin -w /plugin \\
        sketchup-link-blender-debug:4.5 blender --factory-startup --python tests/integration/gui_visualcube_check.py

Steps, each scheduled by a timer so Blender keeps drawing between them (a sleep inside a callback would block the
redraw it waits for):
  1. live-sync the reference model, frame VisualCube in Solid shading coloured by material;
  2. capture the screen (before), set SketchUp's 'Blue' to red over /control/material, live-sync, re-frame;
  3. capture the screen (after), restore 'Blue', and decide on the cube's own pixels (visual_compare.py).
Solid shading with material colours is used rather than Material Preview: on this software-rendered display EEVEE
was still "Compiling EEVEE engine shaders" after 8 s and drew nothing, and Blender exposes no shader-ready API.
Solid needs no shader compile, and it still shows the material's viewport colour, which the import sets from the
SketchUp colour. The settle time is a fixed delay; visual_compare refuses a before frame that does not show the
starting cube, so a too-early capture fails loudly.

Set GUI_VC_SKIP_CHANGE=1 for the negative control: the colour is not changed, and the check must fail.
"""
import json
import os
import queue
import subprocess
import sys
import traceback
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
for p in (REPO, os.path.join(REPO, "integration", "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import addon_utils  # noqa: E402
import bpy  # noqa: E402
from visual_compare import UnusableFrame, cube_change  # noqa: E402

HOST = os.environ.get("SKETCHUP_LINK_HOST", "127.0.0.1")
PORT = int(os.environ.get("SKETCHUP_LINK_PORT", "9876"))
SETTLE = float(os.environ.get("GUI_VC_SETTLE_SECONDS", "8"))
SKIP_CHANGE = os.environ.get("GUI_VC_SKIP_CHANGE") == "1"
# The cube's starting colour on screen. Solid shading's lighting depends on the view, so by default it is read
# from the before frame at the cube's projected centre; set CUBE_RGB to pin it.
CUBE_RGB = [int(v) for v in os.environ["CUBE_RGB"].split()] if os.environ.get("CUBE_RGB") else None
CMP_W, CMP_H = 480, 270  # comparison resolution
MIN_FRACTION = float(os.environ.get("MIN_FRACTION", "0.5"))
OUT = os.environ.get("GUI_VC_OUT", "/tmp")
AFTER_COLOR = {"r": 220, "g": 60, "b": 60}

addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402


def finish(code, msg):
    print(msg, flush=True)
    sys.stdout.flush()
    os._exit(code)  # quit_blender() would exit 0 regardless; the verdict must reach the exit code


def sync():
    ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
    ls._sync_state["queue"] = queue.SimpleQueue()
    ls._sync_state["running"] = True
    ls._sync_state["queue"].put(fetch_model_json_tcp(HOST, PORT, False))
    ls._sync_timer()


def cube_screen_point(ob):
    """Screen pixel (x from left, y from top) of the cube's bounding-box centre in the 3D view."""
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    from mathutils import Vector
    centre = ob.matrix_world @ (sum((Vector(c) for c in ob.bound_box), Vector()) / 8)
    for w in bpy.context.window_manager.windows:
        for area in w.screen.areas:
            if area.type == "VIEW_3D":
                region = next(r for r in area.regions if r.type == "WINDOW")
                xy = location_3d_to_region_2d(region, area.spaces.active.region_3d, centre)
                if xy is not None:
                    return region.x + xy.x, w.height - (region.y + xy.y), w.width, w.height
    return None


def frame_visualcube():
    ob = next((o for o in bpy.data.objects if o.name.startswith(("G-VisualCube", "VisualCube"))
               and o.type == "MESH"), None)
    if ob is None:
        finish(1, "GUI-VISUALCUBE FAIL: no VisualCube mesh after the live sync")
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    for w in bpy.context.window_manager.windows:
        for area in w.screen.areas:
            if area.type == "VIEW_3D":
                shading = area.spaces.active.shading
                shading.type = "SOLID"
                shading.color_type = "MATERIAL"
                region = next(r for r in area.regions if r.type == "WINDOW")
                with bpy.context.temp_override(window=w, area=area, region=region):
                    bpy.ops.view3d.view_selected()
                ob.select_set(False)  # the selection outline would otherwise recolour the cube's edge
                area.tag_redraw()
    return ob


def capture(name):
    """Grab the display Blender draws on, as packed RGB at the comparison resolution."""
    png = os.path.join(OUT, f"gui_vc_{name}.png")
    disp = os.environ.get("DISPLAY", ":99")
    subprocess.run(["bash", "-c", f"xwd -display {disp} -root -silent | convert xwd:- {png}"], check=True)
    raw = subprocess.run(["convert", png, "-resize", f"{CMP_W}x{CMP_H}!", "-depth", "8", "rgb:-"],
                         check=True, capture_output=True).stdout
    return raw


def set_blue(color):
    req = urllib.request.Request(f"http://{HOST}:{PORT}/control/material",
                                 data=json.dumps({"name": "Blue", "color": color}).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status != 200:
            raise RuntimeError(f"/control/material returned {r.status}")


STATE = {"step": 0, "before": None, "original": None}


def run():
    try:
        STATE["step"] += 1
        if STATE["step"] == 1:
            snap = fetch_model_json_tcp(HOST, PORT, False)
            blue = next((m for m in snap["materials"] if m["name"] == "Blue"), None)
            if blue is None:
                finish(1, "GUI-VISUALCUBE FAIL: the reference model has no Blue material")
            STATE["original"] = {k: blue["color"][k] for k in ("r", "g", "b")}
            sync()
            STATE["cube"] = frame_visualcube()
            return SETTLE
        if STATE["step"] == 2:
            STATE["point"] = cube_screen_point(STATE["cube"])
            STATE["before"] = capture("before")
            if not SKIP_CHANGE:
                set_blue(AFTER_COLOR)
            sync()
            frame_visualcube()
            return SETTLE
        after = capture("after")
        set_blue(STATE["original"])
        cube_rgb = CUBE_RGB
        if cube_rgb is None:
            if STATE["point"] is None:
                finish(1, "GUI-VISUALCUBE FAIL: the cube's centre does not project into the 3D view")
            sx, sy, ww, wh = STATE["point"]
            i = (int(sy * CMP_H / wh) * CMP_W + int(sx * CMP_W / ww)) * 3
            cube_rgb = list(STATE["before"][i:i + 3])
            print(f"cube colour at its centre in the before frame: {tuple(cube_rgb)}", flush=True)
        try:
            px, changed, frac = cube_change(STATE["before"], after, cube_rgb, tol=25)
        except UnusableFrame as e:
            finish(1, f"GUI-VISUALCUBE FAIL: {e}")
        if frac < MIN_FRACTION:
            finish(1, f"GUI-VISUALCUBE FAIL: {changed}/{px} cube pixels changed ({frac:.1%} < {MIN_FRACTION:.0%})")
        finish(0, f"GUI-VISUALCUBE OK: {changed}/{px} cube pixels changed colour on screen ({frac:.1%})")
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        finish(1, "GUI-VISUALCUBE FAIL: exception, see traceback")
    return None


bpy.context.preferences.view.show_splash = False
for _name in ("Cube", "Camera", "Light"):  # factory-startup objects; the 2 m cube would hide VisualCube
    if bpy.data.objects.get(_name):
        bpy.data.objects.remove(bpy.data.objects[_name], do_unlink=True)
bpy.app.timers.register(run, first_interval=SETTLE)
