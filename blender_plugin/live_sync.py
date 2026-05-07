"""
live_sync.py — Live sync operators, poll loop, and timer for sketchup-link.

Background daemon thread polls GET /model every N seconds; the main-thread
timer drains the queue (keeping the most recent snapshot) and calls
SceneImporter.load() directly with the queued JSON model.
"""

import queue
import threading

import bpy
from bpy.props import FloatProperty, StringProperty
from bpy.types import Operator, Panel
from mathutils import Matrix, Vector
from .live_adapter import DEFAULT_SOCKET_PATH, JsonModel, fetch_model_json, fetch_model_json_tcp, _build_conn_config
from .log_config import get_logger

_logger = get_logger()

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
            _logger.info(f"Polling SketchUp (interval={interval}s)")
            q.put(fetch_model_json(conn_config=conn_config))
        except Exception:
            _logger.warning("poll failed", exc_info=True)

def _sync_timer() -> "float | None":
    """
    Main-thread timer callback registered with bpy.app.timers.

    Drains the queue (keeping only the freshest snapshot) and triggers a
    live import via SceneImporter.load() directly with the queued JSON.
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

    if latest is not None:
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
        except Exception as e:
            _logger.error(f"live sync import failed: {e}", exc_info=True)

    return state["interval"]


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
