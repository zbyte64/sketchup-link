"""
Live timer hole-refusal check (functionality gap: faces with holes). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_timer_hole_check.py

A face with an inner loop (a hole) has two boundary loops, so no single outline can be walked from its triangles.
The timer must not push such a face: it cannot know the true outline, and pushing a guessed one would store a wrong
face. This check builds a 3 m square with a 1 m hole in SketchUp, imports it, moves a vertex of the holed face in
Blender, and requires that:
  - SketchUp keeps its holed face exactly as it was (same id, same two loops);
  - the refusal is reported as a warning that names the face;
  - the Blender object is reverted to SketchUp's geometry afterwards.
The model is built and removed through the MCP tunnel; the reference model is restored with the shared reset.
"""
import os
import queue
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

import addon_utils  # noqa: E402
import bpy  # noqa: E402
import reference_reset  # noqa: E402
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin import sync_push  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402

HOST = os.environ.get("SKETCHUP_LINK_HOST", "127.0.0.1")
PORT = int(os.environ.get("SKETCHUP_LINK_PORT", "9876"))
INCH = 1.0 / 0.0254

BUILD = f'''
m = Sketchup.active_model
g = m.entities.add_group
g.name = "HoleGroup"
g.entities.add_face([[0,0,0],[{3*INCH},0,0],[{3*INCH},{3*INCH},0],[0,{3*INCH},0]])
g.entities.add_face([[{1*INCH},{1*INCH},0],[{2*INCH},{1*INCH},0],[{2*INCH},{2*INCH},0],[{1*INCH},{2*INCH},0]])
"ok"
'''


def fail(msg):
    print(f"LIVE-TIMER-HOLE FAIL: {msg}")
    sys.exit(1)


def holed_face(snap):
    grp = next((e for e in snap["entities"] if e.get("type") == "Group" and e.get("name") == "HoleGroup"), None)
    if grp is None:
        return None
    return next((f for f in grp.get("entities", []) if f.get("type") == "Face"
                 and len(f.get("loops", [])) == 2), None)


addon_utils.enable("blender_plugin", default_set=True, persistent=False)

reference_reset.reset()
status = 1
try:
    reply = reference_reset.mcp_eval(BUILD)
    if '"ok"' not in reply:
        fail(f"could not build the holed face in SketchUp: {reply[-160:]}")
    ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
    ls._sync_state["running"] = True
    ls._sync_state["queue"] = queue.SimpleQueue()

    def run_timer():
        _snap = fetch_model_json_tcp(HOST, PORT, False)
        _snap["two_way_enabled"] = True  # this check exercises two-way editing
        ls._sync_state["queue"].put(_snap)
        ls._sync_timer()

    run_timer()  # import and record the baseline
    sync_push._warnings.clear()

    before = holed_face(fetch_model_json_tcp(HOST, PORT, False))
    if before is None:
        fail("the holed face (two loops) is not in the snapshot")
    before_id = before["persistent_id"]
    before_loops = sorted(tuple(round(c, 3) for v in loop for c in v) for loop in before["loops"])
    grp_id = next(e for e in fetch_model_json_tcp(HOST, PORT, False)["entities"]
                  if e.get("name") == "HoleGroup")["persistent_id"]

    ob = next((o for o in bpy.data.objects if o.get("skp_persistent_id") == grp_id), None)
    if ob is None:
        fail("the HoleGroup is not an identified Blender object")
    # Move one vertex of the outer loop in Blender: a real edit to the holed face.
    moved = None
    for v in ob.data.vertices:
        w = ob.matrix_world @ v.co
        if abs(w.x) < 1e-3 and abs(w.y) < 1e-3:
            v.co.x += 0.3
            moved = True
            break
    if not moved:
        fail("could not find the outer corner (0,0) to move in Blender")
    ob.data.update()
    run_timer()

    after = holed_face(fetch_model_json_tcp(HOST, PORT, False))
    if after is None:
        fail("the holed face is gone or no longer has two loops: SketchUp was changed for a refused face")
    if after["persistent_id"] != before_id:
        fail(f"the holed face was reshaped (id {before_id} -> {after['persistent_id']}); a holed face must not be pushed")
    after_loops = sorted(tuple(round(c, 3) for v in loop for c in v) for loop in after["loops"])
    if after_loops != before_loops:
        fail("the holed face's loops changed in SketchUp: a refused face must be left exactly as it was")

    refused = [w for w in sync_push.warnings() if "hole" in w.lower() or "two boundary" in w.lower()
               or "no single" in w.lower()]
    if not refused:
        fail(f"the refusal was not reported: warnings are {sync_push.warnings()}")

    # After the refusal the import rebuilds the object from SketchUp, so the local move must be gone.
    ob_now = next((o for o in bpy.data.objects if o.get("skp_persistent_id") == grp_id), None)
    if ob_now is None:
        fail("the imported object is missing after a refusal")
    if any(abs(v.co.x - 0.3 / 1.0) < 1e-6 and abs(v.co.y) < 1e-6 for v in ob_now.data.vertices):
        fail("the refused edit is still in Blender: the object must match SketchUp after a refusal")

    status = 0
    print(f"LIVE-TIMER-HOLE OK: holed face {before_id} left unchanged in SketchUp, refusal reported, edit reverted")
finally:
    try:
        reference_reset.mcp_eval('Sketchup.active_model.entities.grep(Sketchup::Group).each { |g| g.erase! if g.name == "HoleGroup" }; "ok"')
    except Exception:
        pass
    reference_reset.reset()
sys.exit(status)
