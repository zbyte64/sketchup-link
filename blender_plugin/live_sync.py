"""
live_sync.py — Live sync operators, poll loop, and timer for sketchup-link.

Background daemon thread polls GET /model every N seconds; the main-thread
timer drains the queue (keeping the most recent snapshot) and calls
SceneImporter.load() directly with the queued JSON model.
"""

import json
import queue
import threading
import urllib.error
import urllib.request

import bpy
from bpy.props import FloatProperty, StringProperty
from bpy.types import Operator, Panel
from mathutils import Matrix, Vector
from .live_adapter import DEFAULT_SOCKET_PATH, JsonModel, fetch_model_json, fetch_model_json_tcp, _build_conn_config
from .log_config import get_logger
from .scene_importer import SceneImporter

_logger = get_logger()

# Exponential backoff for repeated import failures in _sync_timer.
# After each consecutive failure the delay doubles, starting from
# BACKOFF_BASE_SECONDS, and is capped at BACKOFF_MAX_SECONDS.
# A successful import resets the delay to the normal poll interval.
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 60.0
BACKOFF_MULTIPLIER = 2.0

_sync_state: dict = {
    "running": False,
    "thread": None,
    "stop_event": None,
    "queue": None,
    "conn_config": _build_conn_config(),
    "interval": 2.0,
}


def _poll_loop(
    stop_event: threading.Event,
    q: queue.SimpleQueue,
    conn_config: dict,
    interval: float,
) -> None:
    """Background daemon thread: polls SketchUp and queues model snapshots."""
    while not stop_event.wait(timeout=interval):
        try:
            _logger.debug(f"Polling SketchUp (interval={interval}s)")
            if conn_config["mode"] == "UNIX":
                snapshot = fetch_model_json(conn_config=conn_config)
            else:
                snapshot = fetch_model_json_tcp(
                    conn_config["host"],
                    conn_config["port"],
                    conn_config.get("binary_textures", False),
                )
            q.put(snapshot)
        except Exception:
            _logger.warning("poll failed", exc_info=True)

def _sync_timer() -> "float | None":
    """
    Main-thread timer callback registered with bpy.app.timers.

    Drains the queue (keeping only the freshest snapshot) and triggers a
    live import via SceneImporter.load() directly with the queued JSON.
    On repeated import failures the retry delay backs off exponentially
    (see BACKOFF_* constants) and resets after a successful import.
    Returns None to unregister once the sync has been stopped.
    """
    state = _sync_state
    if not state["running"]:
        return None  # unregisters the timer

    q = state["queue"]
    latest = None
    try:
        while True:
            latest = q.get_nowait()
    except queue.Empty:
        pass

    # Imported-geometry edits are checked on every pass, including passes with no new snapshot,
    # because the edit can happen at any time between imports. Without this the check only ran when
    # a snapshot arrived, so a vertex edit between two polls was never seen.
    try:
        import bpy  # type: ignore[import-not-found]  # Blender-only module
        from . import sync_push as _sp
        _warn_imported_geometry_edits(_sp, bpy, push=True)
    except Exception:
        _logger.warning("imported geometry check skipped", exc_info=True)

    if latest is None:
        return _next_delay(state)

    # Push Blender edits BEFORE importing: the import rebuilds tagged objects, so an edit
    # made since the last sync would otherwise be overwritten before it is sent.
    _push_pending_edits()

    _logger.info(f"Importing model snapshot (queue had data)")
    try:
        importer = SceneImporter()
        importer.set_filename("")
        importer.skp_model = JsonModel(latest)

        options = dict(
            filepath="",
            scenes_as_camera=False,
            import_camera=False,
            reuse_material=True,
            dedub_only=False,
            reuse_existing_groups=False,
            max_instance=1,
            dedub_type="VERTEX",
            import_scene="",
        )
        importer.load(bpy.context, **options)

        # Follow SketchUp viewport if enabled
        try:
            prefs = bpy.context.preferences.addons[__package__].preferences
            if prefs.follow_viewport:
                _apply_viewport(importer.skp_model.camera)
        except Exception:
            _logger.debug("viewport follow skipped", exc_info=True)
        state["failures"] = 0
        # Record the baseline from the geometry this import just built. Checking only before the import
        # would miss a freshly imported object: its first baseline would never be taken.
        try:
            import bpy  # type: ignore[import-not-found]  # Blender-only module
            from . import sync_push as _sp
            _warn_imported_geometry_edits(_sp, bpy, push=False)
        except Exception:
            _logger.warning("imported geometry baseline skipped", exc_info=True)
    except Exception as e:
        state["failures"] = state.get("failures", 0) + 1
        _logger.error(
            f"live sync import failed (consecutive={state['failures']}): {e}",
            exc_info=True,
        )

    return _next_delay(state)


def _push_pending_edits():
    """Capture Blender edits, push them under the SketchUp-wins policy, record warnings.

    Failures are logged and never raised: a push problem must not stop the live import.
    """
    try:
        from . import edit_capture, sync_push
        from .live_adapter import fetch_model_json_tcp
        from .sync_push import SketchUpState

        # Imported geometry edits are reported on every pass, before any early return, so an imported
        # mesh's baseline is recorded and a later vertex edit is caught. bpy is bound here, first, because
        # a later "import bpy" in this function would make the name local and raise UnboundLocalError.

        # Deletions made in Blender: a tracked tagged object that no longer exists. Only ids we
        # synced are considered, so an object we never had cannot be erased by mistake.
        import bpy  # type: ignore[import-not-found]  # Blender-only module
        present = {int(o["skp_persistent_id"]) for o in bpy.data.objects if "skp_persistent_id" in o}
        for pid in edit_capture.removed_ids(set(edit_capture.tracker()._synced.keys()), present):
            _push_delete(pid, sync_push)
            edit_capture.tracker().forget(pid)

        # Adds made in Blender: a mesh object with no SketchUp identity is new geometry. Each
        # polygon is pushed as a face, and the id SketchUp returns is written back so the object is
        # enrolled and never pushed again (echo suppression).
        _push_new_meshes(sync_push, bpy)

        edits = edit_capture.drain_pending()
        if not edits:
            return

        snapshot = {}

        def read_current(pid):
            nonlocal snapshot
            snapshot = fetch_model_json_tcp(_sync_state["conn_config"]["host"],
                                            _sync_state["conn_config"]["port"], False)
            for e in snapshot.get("entities", []):
                if e.get("persistent_id") == pid:
                    # Only entities that carry a transform report one (a face does not). A missing
                    # transform is reported as unknown, not raised: a KeyError here dropped the whole push.
                    transform = e.get("transformation")
                    return SketchUpState(transform=tuple(transform) if transform is not None else None,
                                         color=None)
            return SketchUpState()

        for edit in edits:
            baseline = edit_capture.tracker()._synced.get(edit.persistent_id)
            if baseline is None:
                continue
            result = sync_push.push(
                edit, baseline,
                read_current=read_current,
                send_transform=_post_transform,
                send_material=_post_material,
                material_name_for=lambda pid: None,
            )
            sync_push.record_result(result)
            if result.error:
                _logger.warning(f"push failed: {result.error}")
    except Exception:
        _logger.warning("edit push skipped", exc_info=True)


def _push_new_meshes(sync_push, bpy):
    """Push untagged Blender meshes to SketchUp as faces, one per polygon, and enrol them.

    The face route takes metres in world space, so vertices are transformed by the object's world
    matrix first. Each polygon's loop is converted by geometry_push, so holes and degenerate faces
    are handled there. A polygon that SketchUp accepts gets its id written onto the object; the
    object is enrolled once every polygon has been pushed. Failures are logged, never raised.
    """
    from . import edit_capture, geometry_push
    cc = _sync_state["conn_config"]
    for ob in list(bpy.data.objects):
        # Only user geometry is pushed. A tagged object already has an identity, and an object the
        # importer created carries IMPORT_MARKER (skp_link_import): pushing it back would echo SketchUp's
        # own geometry as new faces on every sync.
        if ob.type != "MESH" or "skp_persistent_id" in ob or ob.get("skp_link_import"):
            continue
        me = ob.data
        coords = [tuple(ob.matrix_world @ v.co) for v in me.vertices]
        loops = [list(p.vertices) for p in me.polygons]
        pids = []
        for face in geometry_push.polygons_to_faces(coords, loops):
            body = json.dumps(face.body()).encode()
            req = urllib.request.Request(f"http://{cc['host']}:{cc['port']}/control/geometry/face",
                                         data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    pids.append(int(json.loads(r.read())["persistent_id"]))
            except Exception:
                _logger.warning(f"face push failed for {ob.name}", exc_info=True)
        if pids:
            # The object's identity is the first face SketchUp created for it. Recording it as synced
            # is what stops the next sync from pushing the same polygons again. The faces and the
            # geometry they were built from are kept, so a later vertex edit can replace them.
            ob["skp_persistent_id"] = pids[0]
            ob["skp_user_faces"] = json.dumps(pids)
            ob["skp_user_geom"] = _geometry_signature(coords, loops)
            edit_capture.tracker().record_sync(pids[0], tuple(v for row in ob.matrix_basis for v in row),
                                               None)
    _replace_modified_meshes(sync_push, bpy)


_import_geometry = {}  # SketchUp id -> (geometry signature, per-face shapes) as the import produced it


def _face_shapes(ob):
    """Per SketchUp face id, the set of world-space corners of the polygons attributed to it."""
    layer = ob.data.attributes.get("skp_face_id")
    if layer is None:
        return {}
    shapes = {}
    for poly in ob.data.polygons:
        corners = shapes.setdefault(int(layer.data[poly.index].value), set())
        for i in poly.vertices:
            corners.add(tuple(round(c, 6) for c in ob.matrix_world @ ob.data.vertices[i].co))
    return {pid: frozenset(c) for pid, c in shapes.items()}


def _warn_imported_geometry_edits(sync_push, bpy, push=True):
    """Push vertex edits on imported (SketchUp-originated) mesh geometry, face by face, or report them.

    Each changed face is rebuilt in its own SketchUp owner through /control/geometry/face/reshape (see
    _reshape_changed_faces). A face that cannot be stored faithfully (concave, or with a hole) is refused,
    and the user is told the edit was not sent to SketchUp.
    The baseline is the geometry as the import produced it, recorded the first time it is seen.

    Loose top-level geometry imports as one object with no SketchUp id of its own (the model is its owner),
    but each of its polygons names its SketchUp face in skp_face_id, which is all a reshape needs. It is
    keyed by object name, which the importer keeps stable ("_(Loose Entity)") across rebuilds.
    """
    for ob in bpy.data.objects:
        if ob.type != "MESH" or not ob.get("skp_link_import"):
            continue
        if "skp_persistent_id" in ob:
            key = int(ob["skp_persistent_id"])
        elif ob.data.attributes.get("skp_face_id") is not None:
            key = f"loose:{ob.name}"
        else:
            continue
        me = ob.data
        coords = [tuple(ob.matrix_world @ v.co) for v in me.vertices]
        loops = [list(p.vertices) for p in me.polygons]
        sig = _geometry_signature(coords, loops)
        # Keyed by SketchUp id in the tracker, not on the object: every live import rebuilds the tagged
        # objects, so a property on the object would not survive to the next pass.
        pid = key
        baseline = _import_geometry.get(pid)
        if baseline is None:
            _import_geometry[pid] = (sig, _face_shapes(ob))
            continue
        if sig != baseline[0]:
            if not push:
                # Post-import pass: record the baseline only. The change is pushed by the pre-import pass,
                # so it is never pushed twice in one timer pass.
                _import_geometry[pid] = (sig, _face_shapes(ob))
                continue
            # Only faces whose own corners moved are reshaped. A reshape rebuilds the face in SketchUp and
            # gives it a new id, so reshaping the untouched faces of a multi-face object (loose geometry has
            # many) would churn their identity for nothing.
            unchanged = {f for f, shape in _face_shapes(ob).items() if baseline[1].get(f) == shape}
            if not _reshape_changed_faces(ob, sync_push, unchanged):
                sync_push.add_warning(
                    f"{ob.name}: vertex edit kept in Blender only (could not be pushed to SketchUp)")
            # Pushed or refused, the baseline is the new geometry (a reshape writes new ids to the layer).
            _import_geometry[pid] = (sig, _face_shapes(ob))


def _reshape_changed_faces(ob, sync_push, unchanged=frozenset()):
    """Push the changed loops of an imported object's faces through /control/geometry/face/reshape.

    Each Blender polygon names its SketchUp face in the skp_face_id layer. Polygons are grouped by face,
    and a face's loop is its polygon's current vertices in world space. Returns True when every changed
    face was reshaped. The reshape returns the new persistent id, which is recorded in the object's face
    map so later syncs attribute its polygons to the new id. Failures are logged and reported as False.
    """
    layer = ob.data.attributes.get("skp_face_id")
    if layer is None:
        return False
    cc = _sync_state["conn_config"]
    # The layer holds the face ids from the last import. An import rebuilds the group, which gives its
    # faces new SketchUp ids, so a stored id can be stale. Resolve each face against the snapshot the
    # live timer fetched for this pass; a face that cannot be found is not pushed.
    current = _current_face_ids(ob)
    by_face = {}
    for poly in ob.data.polygons:
        by_face.setdefault(int(layer.data[poly.index].value), []).append(poly)
    ok = True
    for face_pid, polys in by_face.items():
        if face_pid in unchanged:
            continue
        if face_pid == 0:
            ok = False
            continue
        loop = _face_loop(ob, polys)
        if len(loop) >= 3 and _is_concave(loop):
            # SketchUp's add_face stores a concave loop as a different, self-intersecting boundary, so a
            # reshape of a concave face pushes the wrong outline. Refuse it and say so: the edit stays in Blender.
            _logger.warning(f"face {face_pid} of {ob.name} is concave; not reshaped (SketchUp cannot store it faithfully)")
            sync_push.add_warning(
                f"{ob.name}: concave face edit reverted to the SketchUp geometry (SketchUp cannot store a concave face faithfully)")
            ok = False
            continue
        face_pid = current.get(face_pid, face_pid)
        if len(loop) < 3:
            # The boundary could not be walked as one loop (for example a face with a hole). Refuse to push
            # a guessed outline, and say so: the edit stays in Blender only.
            _logger.warning(f"face {face_pid} of {ob.name} has no single boundary loop; not reshaped")
            ok = False
            continue
        body = json.dumps({"persistent_id": face_pid, "points": loop}).encode()
        req = urllib.request.Request(f"http://{cc['host']}:{cc['port']}/control/geometry/face/reshape",
                                     data=body, method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                new_pid = int(json.loads(r.read())["persistent_id"])
            for p in polys:
                layer.data[p.index].value = new_pid
            _logger.info(f"reshaped SketchUp face {face_pid} -> {new_pid} for {ob.name}")
        except Exception:
            ok = False
            _logger.warning(f"reshape push failed for face {face_pid} of {ob.name}", exc_info=True)
    return ok


def _is_concave(loop):
    """True when a polygon has a reflex vertex: its turns do not all share one orientation.

    The loop is in world space and is treated in the plane it lies in, using its first three points for the
    normal. Collinear turns are ignored. A convex polygon turns the same way at every vertex; a concave one
    turns both ways.
    """
    n = len(loop)
    if n < 4:
        return False

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    # Project onto the plane of the face: pick the two axes with the largest spread.
    xs = [p[0] for p in loop]
    ys = [p[1] for p in loop]
    zs = [p[2] for p in loop]
    spread = {"x": max(xs) - min(xs), "y": max(ys) - min(ys), "z": max(zs) - min(zs)}
    a, b = sorted(spread, key=spread.get, reverse=True)[:2]
    pts = [(p["xyz".index(a)], p["xyz".index(b)]) for p in loop]
    signs = set()
    for i in range(n):
        c = cross(pts[i], pts[(i + 1) % n], pts[(i + 2) % n])
        if abs(c) > 1e-12:
            signs.add(c > 0)
    return len(signs) > 1


def _face_loop(ob, polys):
    """The true boundary of a SketchUp face, walked from its triangles.

    A face is triangulated into Blender polygons. Its boundary is the set of triangle edges used by exactly
    one triangle; walking those edges, oriented by each triangle's winding, gives the outline in order. This
    is exact for concave faces too: a centroid-angle ordering reorders a U-shaped face's notch and pushes a
    different outline with no error. Returns the loop in world space, or [] when the boundary is not a single
    closed chain (a face with a hole), so the caller refuses to push it rather than push a wrong loop.
    """
    from collections import Counter

    def key(i):
        co = ob.matrix_world @ ob.data.vertices[i].co
        return (round(co.x, 6), round(co.y, 6), round(co.z, 6))

    coords = {}
    use = Counter()
    directed = {}
    for p in polys:
        idx = list(p.vertices)
        for i in idx:
            coords[key(i)] = ob.matrix_world @ ob.data.vertices[i].co
        a, b, c = (key(idx[0]), key(idx[1]), key(idx[2])) if len(idx) >= 3 else (None, None, None)
        if a is None:
            return []
        for u, v in ((a, b), (b, c), (c, a)):
            use[frozenset((u, v))] += 1
            directed[frozenset((u, v))] = (u, v)
    nxt = {}
    for k, n in use.items():
        if n != 1:
            continue
        u, v = directed[k]
        if u in nxt:
            return []
        nxt[u] = v
    if not nxt:
        return []
    start = next(iter(nxt))
    walk = [start]
    cur = nxt.get(start)
    while cur is not None and cur != start:
        walk.append(cur)
        cur = nxt.get(cur)
    if cur != start or len(walk) != len(nxt):
        return []
    return [list(coords[k]) for k in walk]


def _current_face_ids(ob):
    """Map each stored SketchUp face id on an imported object to the id that face has now.

    An import rebuilds the group and gives its faces new ids, so a stored id can be stale. A face is
    matched by its vertex set: the face whose current loop has the same vertices is the same face. Only
    faces of the object's own group are considered. A stored id that is still live maps to itself. A face
    that cannot be matched is left out, so it is not pushed under a stale id.
    """
    try:
        snap = fetch_model_json_tcp(_sync_state["conn_config"]["host"], _sync_state["conn_config"]["port"], False)
    except Exception:
        return {}
    layer = ob.data.attributes.get("skp_face_id")
    if layer is None:
        return {}
    stored = {int(layer.data[i].value) for i in range(len(layer.data))} - {0}

    def key(verts):
        return frozenset(tuple(round(c, 3) for c in v) for v in verts)

    current = {}

    def walk(entities):
        for e in entities:
            if e.get("type") == "Face":
                current[int(e["persistent_id"])] = key(e.get("vertices", []))
            walk(e.get("entities", []) or [])

    walk(snap.get("entities", []))
    for d in snap.get("component_definitions", {}).values():
        walk(d.get("entities", []) or [])

    # The stored face's vertices are the loop its polygons had at import, taken from the current mesh's
    # attribution: each stored id's polygons give the loop that was pushed, so match on that loop.
    mapping = {}
    for pid in stored:
        if pid in current:
            mapping[pid] = pid
            continue
        polys = [p for p in ob.data.polygons if int(layer.data[p.index].value) == pid]
        if not polys:
            continue
        loop = key([ob.matrix_world @ ob.data.vertices[i].co for i in polys[0].vertices])
        for cur_pid, cur_key in current.items():
            if cur_key == loop:
                mapping[pid] = cur_pid
                break
    return mapping


def _geometry_signature(coords, loops):
    """A stable signature of a mesh's world geometry: the rounded vertex loops, in order."""
    return json.dumps([[tuple(round(c, 6) for c in coords[i]) for i in loop] for loop in loops])


def _replace_modified_meshes(sync_push, bpy):
    """Delete-and-re-add for a user mesh whose geometry changed since it was pushed.

    The design models a vertex edit as delete-and-re-add: the object's old faces are erased and its
    current polygons are pushed as new faces, with the first new id written back as its identity.
    Only objects this module enrolled (they carry skp_user_faces) are touched.
    """
    from . import edit_capture, geometry_push
    cc = _sync_state["conn_config"]
    for ob in list(bpy.data.objects):
        if ob.type != "MESH" or "skp_user_faces" not in ob:
            continue
        me = ob.data
        coords = [tuple(ob.matrix_world @ v.co) for v in me.vertices]
        loops = [list(p.vertices) for p in me.polygons]
        if _geometry_signature(coords, loops) == ob.get("skp_user_geom"):
            continue
        old_pids = [int(p) for p in json.loads(ob["skp_user_faces"])]
        for pid in old_pids:
            _push_delete(pid, sync_push)
            edit_capture.tracker().forget(pid)
        new_pids = []
        for face in geometry_push.polygons_to_faces(coords, loops):
            body = json.dumps(face.body()).encode()
            req = urllib.request.Request(f"http://{cc['host']}:{cc['port']}/control/geometry/face",
                                         data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    new_pids.append(int(json.loads(r.read())["persistent_id"]))
            except Exception:
                _logger.warning(f"re-add push failed for {ob.name}", exc_info=True)
        if new_pids:
            ob["skp_persistent_id"] = new_pids[0]
            ob["skp_user_faces"] = json.dumps(new_pids)
            ob["skp_user_geom"] = _geometry_signature(coords, loops)
            edit_capture.tracker().record_sync(new_pids[0], tuple(v for row in ob.matrix_basis for v in row),
                                               None)


def _push_delete(persistent_id, sync_push):
    """Erase a SketchUp entity removed in Blender, through /control/geometry/delete.

    SketchUp wins: the delete is sent only if SketchUp still has the entity; a 404 means it is
    already gone, which is success. Failures are logged and never raised.
    """
    cc = _sync_state["conn_config"]
    body = json.dumps({"persistent_id": persistent_id}).encode()
    req = urllib.request.Request(f"http://{cc['host']}:{cc['port']}/control/geometry/delete",
                                 data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            _logger.info(f"erased SketchUp entity {persistent_id} removed in Blender ({r.status})")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            _logger.info(f"SketchUp entity {persistent_id} already gone")
        else:
            _logger.warning(f"delete push failed for {persistent_id}: HTTP {e.code}")
    except Exception:
        _logger.warning(f"delete push failed for {persistent_id}", exc_info=True)


def _post_transform(persistent_id, transformation):
    """POST a transform to /control/geometry/transform on the configured host."""
    import json as _json
    import urllib.request as _ur
    cc = _sync_state["conn_config"]
    body = _json.dumps({"persistent_id": persistent_id, "transformation": list(transformation)}).encode()
    req = _ur.Request(f"http://{cc['host']}:{cc['port']}/control/geometry/transform", data=body,
                      method="POST", headers={"Content-Type": "application/json"})
    try:
        with _ur.urlopen(req, timeout=10) as r:
            return r.status
    except Exception:
        return 0


def _post_material(name, color):
    """POST a material colour to /control/material on the configured host."""
    import json as _json
    import urllib.request as _ur
    cc = _sync_state["conn_config"]
    body = _json.dumps({"name": name, "color": {"r": color[0], "g": color[1], "b": color[2]}}).encode()
    req = _ur.Request(f"http://{cc['host']}:{cc['port']}/control/material", data=body,
                      method="POST", headers={"Content-Type": "application/json"})
    try:
        with _ur.urlopen(req, timeout=10) as r:
            return r.status
    except Exception:
        return 0


def _next_delay(state: dict) -> float:
    """Return the timer delay: normal interval, or backed-off after failures."""
    failures = state.get("failures", 0)
    if failures <= 0:
        return state["interval"]
    delay = BACKOFF_BASE_SECONDS * (BACKOFF_MULTIPLIER ** (failures - 1))
    return min(max(delay, state["interval"]), BACKOFF_MAX_SECONDS)


def _apply_viewport(camera):
    """Set the active 3D viewport to match the SketchUp camera."""
    pos, target, up = camera.GetOrientation()
    if pos == target:
        return  # degenerate, skip

    z = Vector(pos) - Vector(target)  # direction from target to camera
    x = Vector(up).cross(z)
    y = z.cross(x)
    x.normalize()
    y.normalize()
    z.normalize()

    # Build view matrix from axes
    # region_3d.view_matrix is the inverse of the camera world matrix
    m = Matrix((
        (x.x, y.x, z.x, pos[0]),
        (x.y, y.y, z.y, pos[1]),
        (x.z, y.z, z.z, pos[2]),
        (0,   0,   0,  1),
    ))
    view_matrix = m.inverted()

    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            r3d = area.spaces[0].region_3d
            r3d.view_matrix = view_matrix
            r3d.view_perspective = "PERSP" if camera.perspective else "ORTHO"
            r3d.view_distance = (Vector(pos) - Vector(target)).length
            break


class SketchUpStartLiveSync(Operator):
    """Start continuously syncing the open SketchUp model into Blender"""

    bl_idname = "import_scene.skp_start_live_sync"
    bl_label = "Start SketchUp Live Sync"

    interval: FloatProperty(
        name="Poll Interval (s)",
        default=2.0,
        min=0.5,
    )

    def execute(self, context):
        state = _sync_state
        if state["running"]:
            self.report({"INFO"}, "Already running")
            return {"CANCELLED"}

        # Read transport config from addon preferences
        prefs = context.preferences.addons[__package__].preferences
        conn_config = _build_conn_config(prefs)

        stop_event = threading.Event()
        q: queue.SimpleQueue = queue.SimpleQueue()
        state.update(
            running=True,
            conn_config=conn_config,
            interval=self.interval,
            stop_event=stop_event,
            queue=q,
        )
        state["thread"] = threading.Thread(
            target=_poll_loop,
            args=(stop_event, q, conn_config, self.interval),
            daemon=True,
        )
        state["thread"].start()
        bpy.app.timers.register(_sync_timer, first_interval=self.interval)
        self.report({"INFO"}, "SketchUp live sync started")
        return {"FINISHED"}


class SketchUpStopLiveSync(Operator):
    """Stop the SketchUp live sync"""

    bl_idname = "import_scene.skp_stop_live_sync"
    bl_label = "Stop SketchUp Live Sync"

    def execute(self, context):
        state = _sync_state
        if not state["running"]:
            self.report({"INFO"}, "Not running")
            return {"CANCELLED"}
        state["running"] = False
        if state["stop_event"]:
            state["stop_event"].set()
        self.report({"INFO"}, "SketchUp live sync stopped")
        return {"FINISHED"}


class SketchUpClearSyncWarnings(Operator):
    """Dismiss the sync warnings shown in the panel"""

    bl_idname = "import_scene.skp_clear_sync_warnings"
    bl_label = "Dismiss Sync Warnings"

    def execute(self, context):
        from . import sync_push as _sp
        _sp.clear_warnings()
        return {"FINISHED"}


class SKETCHUP_PT_LiveSync(Panel):
    bl_label = "SketchUp Live Sync"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "SketchUp"

    def draw(self, context):
        layout = self.layout
        state = _sync_state
        prefs = context.preferences.addons[__package__].preferences
        if state["running"]:
            layout.operator("import_scene.skp_stop_live_sync", icon="PAUSE")
            cc = state["conn_config"]
            if cc["mode"] == "UNIX":
                layout.label(text=f"Socket: {cc['socket_path']}")
            else:
                layout.label(text=f"TCP: {cc['host']}:{cc['port']}")
                if cc.get("binary_textures"):
                    layout.label(text="Binary textures: ON")
            layout.label(text=f"Polling every {state['interval']}s")
            layout.prop(prefs, "follow_viewport")
        else:
            op = layout.operator("import_scene.skp_start_live_sync", icon="PLAY")
            op.interval = 2.0
 
        from . import sync_push as _sp
        warn = _sp.warnings()
        if warn:
            layout.separator()
            layout.label(text=f"Sync warnings ({len(warn)}): SketchUp wins", icon="ERROR")
            for w in warn[-3:]:
                layout.label(text=w[:90])
            layout.operator("import_scene.skp_clear_sync_warnings", icon="X")

        layout.separator()
        layout.label(text="- Quick Render -")
        row = layout.row(align=True)
        row.scale_y = 1.5
        row.operator("sketchup.quick_render", icon="RENDER_STILL", text="Quick Render")
        row = layout.row(align=True)
        row.scale_y = 1.0
        row.operator("sketchup.quick_render_viewport", icon="RENDER_WINDOW", text="Viewport Render")
        if state["running"] and prefs:
            row = layout.row()
            row.prop(prefs, "render_samples", text="Samples")
 
class SketchUpQuickRender(Operator):
    """Render the current scene using the SketchUp camera and addon preferences"""
 
    bl_idname = "sketchup.quick_render"
    bl_label = "Quick Render (SketchUp)"
    bl_options = {"REGISTER"}
 
    @classmethod
    def poll(cls, context):
        return _sync_state["running"]
 
    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        scene = context.scene
 
        # Apply render settings from preferences
        scene.render.engine = prefs.render_engine
        scene.render.resolution_x = prefs.render_resolution_x
        scene.render.resolution_y = prefs.render_resolution_y
        scene.render.file_format = prefs.render_file_format
        scene.render.filepath = prefs.render_output_dir
 
        # Set render samples for Cycles/Eevee
        if prefs.render_engine == "CYCLES":
            scene.cycles.samples = prefs.render_samples
            if hasattr(scene.cycles, "use_denoising"):
                scene.cycles.use_denoising = prefs.render_denoise
        elif prefs.render_engine == "BLENDER_EEVEE_NEXT":
            scene.eevee.taa_render_samples = prefs.render_samples
 
        # Switch to camera view
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces[0].region_3d.view_perspective = "CAMERA"
                break
 
        # Trigger render
        bpy.ops.render.render("INVOKE_DEFAULT", write_still=True)
 
        self.report({"INFO"}, "Quick render started")
        return {"FINISHED"}
 
 
class SketchUpQuickRenderViewport(Operator):
    """Render the current viewport (no file saved)"""
 
    bl_idname = "sketchup.quick_render_viewport"
    bl_label = "Quick Viewport Render"
    bl_options = {"REGISTER"}
 
    @classmethod
    def poll(cls, context):
        return _sync_state["running"]
 
    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        scene = context.scene
 
        # Apply render settings from preferences
        scene.render.engine = prefs.render_engine
        scene.render.resolution_x = prefs.render_resolution_x
        scene.render.resolution_y = prefs.render_resolution_y
 
        # Set render samples
        if prefs.render_engine == "CYCLES":
            scene.cycles.samples = prefs.render_samples
            if hasattr(scene.cycles, "use_denoising"):
                scene.cycles.use_denoising = prefs.render_denoise
        elif prefs.render_engine == "BLENDER_EEVEE_NEXT":
            scene.eevee.taa_render_samples = prefs.render_samples
 
        # Switch to camera view
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces[0].region_3d.view_perspective = "CAMERA"
                break
 
        # Open render window (no file written)
        bpy.ops.render.render("INVOKE_DEFAULT", write_still=False)
 
        self.report({"INFO"}, "Viewport render opened")
        return {"FINISHED"}
 
 
class SKETCHUP_PT_RenderSettings(Panel):
    bl_label = "SketchUp Render Settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "SketchUp"
    bl_options = {"DEFAULT_CLOSED"}
 
    def draw(self, context):
        layout = self.layout
        prefs = context.preferences.addons[__package__].preferences
 
        layout.label(text="- Output -")
        row = layout.row()
        row.use_property_split = True
        row.prop(prefs, "render_resolution_x")
        row = layout.row()
        row.use_property_split = True
        row.prop(prefs, "render_resolution_y")
        row = layout.row()
        row.use_property_split = True
        row.prop(prefs, "render_file_format")
        row = layout.row()
        row.use_property_split = True
        row.prop(prefs, "render_output_dir")
 
        layout.separator()
        layout.label(text="- Sampling -")
        row = layout.row()
        row.use_property_split = True
        row.prop(prefs, "render_samples")
        row = layout.row()
        row.use_property_split = True
        row.prop(prefs, "render_denoise")
 
        layout.separator()
        layout.label(text="- Lighting -")
        row = layout.row()
        row.use_property_split = True
        row.prop(prefs, "import_sun_light")
        row = layout.row()
        row.use_property_split = True
        row.prop(prefs, "world_strength")
