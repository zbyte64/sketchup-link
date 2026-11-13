"""
Live back-texture check (a face textured only on its back). Runs INSIDE Blender:

    blender --background --factory-startup --python tests/integration/live_back_texture_check.py

A face whose front is unpainted imports with its back material (live_back_material_check). When that material
has a texture, its placement is the back side's: SketchUp maps each side separately. Builds such a face with a
back mapping scaled x2 (so it differs from the front's), and asserts that the snapshot carries back_uvs and that
every imported polygon corner of that face has the back side's UV for its point, not the front's.
The reference model is restored before and after.
"""
import json
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
    print(f"LIVE-BACK-TEXTURE FAIL: {msg}")
    sys.exit(1)


# A 2x2 24-bit BMP written into the VM's temp directory, then used as the material's texture. The back side is
# positioned so 1 m of model space spans 2 texture repeats, which the front's default mapping does not do.
BUILD = r'''
px = [[255,0,0],[0,255,0],[0,0,255],[255,255,0]]
rows = [px[2] + px[3], px[0] + px[1]].map { |r| r.each_slice(3).map { |p| p.reverse }.flatten.pack("C*") + "\0\0" }
img = rows.join
bmp = "BM" + [54 + img.bytesize, 0, 54, 40, 2, 2, 1, 24, 0, img.bytesize, 2835, 2835, 0, 0].pack("VVVVl<l<vvVVl<l<VV") + img
path = File.join(ENV["TEMP"] || ENV["TMP"] || "/tmp", "sketchup_link_back_tex.bmp")
File.binwrite(path, bmp)
m = Sketchup.active_model
mat = m.materials.add("BackTex")
mat.texture = path
mat.texture.size = [1.m, 1.m]
f = m.entities.add_face([[2.m, 0, 1.m], [3.m, 0, 1.m], [3.m, 1.m, 1.m], [2.m, 1.m, 1.m]])
f.material = nil
f.back_material = mat
pts = [Geom::Point3d.new(2.m, 0, 1.m), Geom::Point3d.new(0, 0, 0), Geom::Point3d.new(3.m, 0, 1.m), Geom::Point3d.new(2, 0, 0)]
f.position_material(mat, pts, false)
f.persistent_id.to_s
'''

addon_utils.enable("blender_plugin", default_set=True, persistent=False)
from blender_plugin import live_sync as ls  # noqa: E402
from blender_plugin.live_adapter import fetch_model_json_tcp  # noqa: E402

reference_reset.reset()
reference_reset.verify()
status = 1
try:
    reply = reference_reset.mcp_eval(BUILD)
    snap = fetch_model_json_tcp(HOST, PORT, False)
    face = next((e for e in snap["entities"] if e.get("type") == "Face" and e.get("back_material") == "BackTex"),
                None)
    if face is None:
        fail(f"the back-textured face was not built: {reply[-200:]}")
    back = face.get("back_uvs")
    if not back:
        fail("the snapshot has no back_uvs for a face textured only on its back")
    front = face["uvs"]
    if all(abs(a - b) < 1e-6 for fu, bu in zip(front, back) for a, b in zip(fu, bu)):
        fail("the back UVs equal the front UVs, so this check could not tell them apart")
    by_point = {tuple(round(c, 4) for c in v): tuple(uv) for v, uv in zip(face["vertices"], back)}

    ls._sync_state["conn_config"] = {"mode": "TCP", "host": HOST, "port": PORT, "binary_textures": False}
    ls._sync_state["running"] = True
    ls._sync_state["queue"] = queue.SimpleQueue()
    ls._sync_state["queue"].put(snap)
    ls._sync_timer()

    checked = 0
    for ob in bpy.data.objects:
        layer = ob.data.attributes.get("skp_face_id") if ob.type == "MESH" else None
        if layer is None:
            continue
        polys = [p for p in ob.data.polygons if int(layer.data[p.index].value) == face["persistent_id"]]
        if not polys:
            continue
        if not ob.data.uv_layers:
            fail(f"{ob.name} has no UV layer, so the back texture has no placement")
        uv = ob.data.uv_layers[0].data
        for p in polys:
            mat = ob.data.materials[p.material_index]
            if mat is None or mat.name != "BackTex":
                fail(f"polygon {p.index} uses {mat and mat.name!r}, not BackTex")
            for li in p.loop_indices:
                co = tuple(round(c, 4) for c in ob.matrix_world @ ob.data.vertices[ob.data.loops[li].vertex_index].co)
                want = by_point.get(co)
                if want is None:
                    fail(f"imported corner {co} is not a point of the SketchUp face")
                got = tuple(uv[li].uv)
                if any(abs(a - b) > 1e-4 for a, b in zip(got, want)):
                    fail(f"corner {co} has UV {tuple(round(c, 4) for c in got)}, the back side's is {want}")
                checked += 1
    if checked == 0:
        fail("no imported polygon is attributed to the back-textured face")

    status = 0
    print(f"LIVE-BACK-TEXTURE OK: {checked} corner(s) carry the back side's UVs, back material BackTex")
finally:
    reference_reset.reset()
    reference_reset.verify()
sys.exit(status)
