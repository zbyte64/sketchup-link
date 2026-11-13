"""
The one reset every live check uses. Restores the SketchUp reference model to its factory state.

A reset is the full purge over the MCP tunnel (entities, definitions, materials and pages), followed by a
rebuild. A bare rebuild stacks duplicates, so it is never used alone. The purge string is read from the e2e
fixture so the two cannot drift apart.

    python3 tests/integration/reference_reset.py        # reset and verify, exits 0 on a clean model
"""
import json
import os
import re
import socket
import sys
import urllib.request

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
BASE = os.environ.get("SKETCHUP_LINK_BASE", "http://127.0.0.1:9876")
MCP_PORT = int(os.environ.get("MCP_LOCAL_PORT", "9878"))


def purge_code():
    src = open(os.path.join(REPO, "tests", "bdd", "conftest.py"), encoding="utf-8").read()
    purge = re.search(r'_PURGE_ALL = \((.*?)\n\)', src, re.S)
    if purge is None:
        raise RuntimeError("could not read _PURGE_ALL from the e2e fixture")
    return "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', purge.group(1)))


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


def reset():
    """Purge, verify the purge left nothing behind, rebuild. Raises RuntimeError on an incomplete reset."""
    reply = mcp_eval(purge_code())
    if '"0,0,0,0"' not in reply:
        raise RuntimeError(f"reference reset incomplete: {reply[-160:]}")
    req = urllib.request.Request(BASE + "/test_model", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        if r.status != 200:
            raise RuntimeError(f"rebuild returned HTTP {r.status}")


def verify():
    """The rebuilt model has the reference groups, scenes and materials, and no duplicates."""
    d = json.loads(urllib.request.urlopen(BASE + "/model", timeout=30).read())
    groups = sorted(e.get("name") for e in d["entities"] if e.get("type") == "Group")
    materials = sorted(m["name"] for m in d["materials"])
    if groups != ["FurnitureGroup", "VisualCube"]:
        raise RuntimeError(f"reference groups are {groups}")
    if materials != ["Blue", "Red"]:
        raise RuntimeError(f"reference materials are {materials}")
    if len(d.get("scenes", [])) != 2:
        raise RuntimeError(f"reference has {len(d.get('scenes', []))} scenes, expected 2")


if __name__ == "__main__":
    try:
        reset()
        verify()
    except Exception as e:  # report and fail: a dirty reference must never be used silently
        print(f"REFERENCE-RESET FAIL: {e}")
        sys.exit(1)
    print("REFERENCE-RESET OK: the reference model is clean")
    sys.exit(0)
