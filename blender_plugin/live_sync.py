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
from mathutils import Matrix

from .live_adapter import DEFAULT_SOCKET_PATH, JsonModel, fetch_model_json
from .scene_importer import SceneImporter


_sync_state: dict = {
    "running": False,
    "thread": None,
    "stop_event": None,
    "queue": None,
    "socket_path": DEFAULT_SOCKET_PATH,
    "interval": 2.0,
}


def _poll_loop(
    stop_event: threading.Event,
    q: queue.SimpleQueue,
    socket_path: str,
    interval: float,
) -> None:
    """Background daemon thread: polls SketchUp and queues model snapshots."""
    while not stop_event.wait(timeout=interval):
        try:
            q.put(fetch_model_json(socket_path))
        except Exception:
            pass  # SketchUp not running — skip silently


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
        except Exception as e:
            print(f"[sketchup-link] live sync import error: {e}")

    return state["interval"]


class SketchUpStartLiveSync(Operator):
    """Start continuously syncing the open SketchUp model into Blender"""

    bl_idname = "import_scene.skp_start_live_sync"
    bl_label = "Start SketchUp Live Sync"

    socket_path: StringProperty(
        name="Socket Path",
        default=DEFAULT_SOCKET_PATH,
    )
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

        stop_event = threading.Event()
        q: queue.SimpleQueue = queue.SimpleQueue()
        state.update(
            running=True,
            socket_path=self.socket_path,
            interval=self.interval,
            stop_event=stop_event,
            queue=q,
        )
        state["thread"] = threading.Thread(
            target=_poll_loop,
            args=(stop_event, q, self.socket_path, self.interval),
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
        if state["running"]:
            layout.operator("import_scene.skp_stop_live_sync", icon="PAUSE")
            layout.label(text=f"Socket: {state['socket_path']}")
            layout.label(text=f"Polling every {state['interval']}s")
        else:
            op = layout.operator("import_scene.skp_start_live_sync", icon="PLAY")
            op.socket_path = DEFAULT_SOCKET_PATH
            op.interval = 2.0
