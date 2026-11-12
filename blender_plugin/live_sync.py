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
                    return SketchUpState(transform=tuple(e["transformation"]), color=None)
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
