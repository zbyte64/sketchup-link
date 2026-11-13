"""
Live timer concave reshape check (two-way mesh edits, boundary correctness). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_timer_concave_check.py

A U-shaped face has a notch whose vertices lie at angles from the centroid that do not follow the boundary,
so ordering its vertices by angle yields a different polygon with the same vertices, and the wrong one
does not self-intersect. This check builds the U in SketchUp, imports it, edits one vertex in Blender, and
requires the reshaped SketchUp face to have exactly the edges of the true edited boundary.
The reference model is restored with the full purge before and after.
"""
import json
import math
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

import addon_utils  # noqa: E402
import bpy  # noqa: E402

HOST = os.environ.get("SKETCHUP_LINK_HOST", "127.0.0.1")
PORT = int(os.environ.get("SKETCHUP_LINK_PORT", "9876"))
BASE = f"http://{HOST}:{PORT}"
MCP_PORT = int(os.environ.get("MCP_LOCAL_PORT", "9878"))

# The U's true boundary, in order (metres), with the notch between x=1 and x=2.
U = [(0.0, 0.0), (0.0, 3.0), (1.0, 3.0), (1.0, 1.0), (2.0, 1.0), (2.0, 3.0), (3.0, 3.0), (3.0, 0.0)]


def fail(msg):
    print(f"LIVE-TIMER-CONCAVE FAIL: {msg}")
    sys.exit(1)


def post(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body or {}).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, json.loads(r.read() or b"{}")


def model():
    return json.loads(urllib.request.urlopen(BASE + "/model", timeout=30).read())


def edges(poly):
    n = len(poly)
    return {frozenset((tuple(round(c, 3) for c in poly[i]), tuple(round(c, 3) for c in poly[(i + 1) % n])))
            for i in range(n)}


def mcp_eval(code):
    s = socket.create_connection(("127.0.0.1", MCP_PORT), timeout=60)
    s.sendall((json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "eval_ruby", "arguments": {"code": code}}}) + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        c = s.recv(65536)
        if not c:
            break
        buf += c
    s.close()
    return buf.decode(errors="replace")


def reset_reference():
    src = open(os.path.join(REPO, "tests", "bdd", "conftest.py"), encoding="utf-8").read()
    purge = re.search(r'_PURGE_ALL = \((.*?)\n\)', src, re.S).group(1)
    code = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', purge))
    reply = mcp_eval(code)
    if '"0,0,0,0"' not in reply:
        raise RuntimeError(f"reference reset incomplete: {reply[-160:]}")
    post("/test_model")


def u_face_in_model():
    """The face built from the U, found inside UGroup by its vertex set."""
    want = {tuple(round(c, 3) for c in (x, y, 0.0)) for x, y in U}
    grp = next((e for e in model()["entities"] if e.get("type") == "Group" and e.get("name") == "UGroup"), None)
    if grp is None:
        return None
    for e in grp.get("entities", []):
        if e.get("type") == "Face" and {tuple(round(c, 3) for c in v) for v in e.get("vertices", [])} == want:
            return e
    return None


addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402


def run_timer():
    ls._sync_state["queue"].put(fetch_model_json_tcp(HOST, PORT, False))
    ls._sync_timer()


reset_reference()
status = 1
try:
    # Build the U INSIDE a group. A top-level face is imported into an unidentified loose-entity mesh, which
    # the timer never pushes; a face inside a group is imported into an identified object, which it does.
    # SketchUp stores inches; the snapshot reports metres. Build the U in inches (metres / 0.0254), so the
    # stored face is the U of the same size in metres. Building it in raw metres scaled it by 1/0.0254.
    inch = 1.0 / 0.0254
    pts = ", ".join(f"[{x * inch}, {y * inch}, 0.0]" for x, y in U)
    mcp_eval(f'm = Sketchup.active_model; g = m.entities.add_group; g.name = "UGroup"; '
             f'g.entities.add_face([{pts}]); "ok"')
    ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
    ls._sync_state["running"] = True
    ls._sync_state["queue"] = queue.SimpleQueue()
    run_timer()

    face = u_face_in_model()
    if face is None:
        fail("the U face was not created in SketchUp")
    u_pid = face["persistent_id"]

    # The timer pushes only objects that carry a SketchUp identity and the import marker. Select the imported
    # object attributed to the U's face AND carrying that identity; a loose, unidentified object is never pushed.
    ob = next((o for o in bpy.data.objects
               if o.type == "MESH" and "skp_persistent_id" in o and o.get("skp_link_import")
               and o.data.attributes.get("skp_face_id")
               and u_pid in {int(o.data.attributes["skp_face_id"].data[i].value)
                             for i in range(len(o.data.polygons))}), None)
    if ob is None:
        fail("the U face is not attributed to any identified, imported Blender object")

    # Move the notch's inner corner (1,1) to (1.0, 1.5) in Blender: a real change to the U's boundary.
    target = None
    for v in ob.data.vertices:
        w = ob.matrix_world @ v.co
        if abs(w.x - 1.0) < 1e-3 and abs(w.y - 1.0) < 1e-3:
            target = v
            break
    if target is None:
        fail("could not find the notch corner (1,1) in the Blender mesh")
    target.co.y += 0.5
    ob.data.update()

    run_timer()

    # The true edited boundary: the notch corner is now at (1.0, 1.5).
    edited = [(x, 1.5) if (abs(x - 1.0) < 1e-3 and abs(y - 1.0) < 1e-3) else (x, y) for x, y in U]
    want_edges = edges([(x, y, 0.0) for x, y in edited])

    # The reshape replaces the original loop, so the reshaped face is found in UGroup by the EDITED boundary's
    # vertex set. Its edges are then compared with the true edited boundary.
    edited_set = {tuple(round(c, 3) for c in (x, y, 0.0)) for x, y in edited}
    grp = next(e for e in model()["entities"] if e.get("type") == "Group" and e.get("name") == "UGroup")
    after = next((f for f in grp.get("entities", []) if f.get("type") == "Face"
                  and {tuple(round(c, 3) for c in v) for v in f.get("vertices", [])} == edited_set), None)
    if after is None:
        cands = [f["persistent_id"] for f in grp.get("entities", []) if f.get("type") == "Face"]
        fail(f"no face in UGroup has the edited boundary's vertices; UGroup faces: {cands}")
    got_edges = edges(after["vertices"])
    if got_edges != want_edges:
        fail(f"the reshaped face has the wrong boundary: {len(got_edges ^ want_edges)} edge(s) differ "
             f"from the true boundary of the edited U")

    status = 0
    print(f"LIVE-TIMER-CONCAVE OK: concave U reshaped to its true boundary (face {u_pid} -> {after['persistent_id']})")
finally:
    reset_reference()
sys.exit(status)
