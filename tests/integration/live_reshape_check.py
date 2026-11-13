"""
Live SketchUp reshape check (gap 5, two-way mesh edits). Runs on the host, not in Blender:

    uv run pytest-free script: python3 tests/integration/live_reshape_check.py

Reshapes a face inside an imported group through /control/geometry/face/reshape and asserts that:
  - the old id is gone and the new id is a face of the SAME owning group;
  - the group still has the same number of faces (no face was lost or duplicated);
  - the material carries across the reshape;
  - the new face has the requested loop.
The reference model is restored with the full purge before and after.
Exit 0 on success, 1 on failure.
"""
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
BASE = os.environ.get("SKETCHUP_LINK_BASE", "http://127.0.0.1:9876")
MCP_PORT = int(os.environ.get("MCP_LOCAL_PORT", "9878"))


def fail(msg):
    print(f"LIVE-RESHAPE FAIL: {msg}")
    sys.exit(1)


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def model():
    return json.loads(urllib.request.urlopen(BASE + "/model", timeout=30).read())


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
    post("/test_model", {})


def group_faces(d):
    grp = next(e for e in d["entities"] if e.get("type") == "Group" and e.get("name") == "FurnitureGroup")
    return grp, [e for e in grp["entities"] if e.get("type") == "Face"]


status = 1
reset_reference()
try:
    d = model()
    grp, faces = group_faces(d)
    before_count = len(faces)
    target = faces[0]
    pid = target["persistent_id"]
    material_before = target.get("material")
    new_loop = [[0.0, 0.0, 0.0], [1.4, 0.0, 0.0], [0.0, 1.4, 0.0]]

    code, body = post("/control/geometry/face/reshape", {"persistent_id": pid, "points": new_loop})
    if code != 200:
        fail(f"reshape returned HTTP {code}: {body}")
    new_pid = body["persistent_id"]
    if new_pid == pid:
        fail("the reshaped face kept its old id; SketchUp was expected to assign a new one")

    d2 = model()
    grp2, faces2 = group_faces(d2)
    ids2 = {f["persistent_id"] for f in faces2}
    if pid in ids2:
        fail(f"the old face {pid} is still in the group after the reshape")
    if new_pid not in ids2:
        fail(f"the new face {new_pid} is not a face of the owning group")
    if len(faces2) != before_count:
        fail(f"face count changed from {before_count} to {len(faces2)}; a face was lost or duplicated")
    new = next(f for f in faces2 if f["persistent_id"] == new_pid)
    if new.get("material") != material_before:
        fail(f"material changed from {material_before} to {new.get('material')}")
    got = sorted(tuple(round(c, 3) for c in v) for v in new["vertices"])
    want = sorted(tuple(round(c, 3) for c in v) for v in new_loop)
    if got != want:
        fail(f"new face loop {got} does not match the requested {want}")

    print(f"LIVE-RESHAPE OK: face {pid} -> {new_pid} in its group, material kept, loop applied")
    status = 0
finally:
    reset_reference()
sys.exit(status)
