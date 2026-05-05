"""SketchUp Addon Preferences — extracted from the original scene_importer."""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import AddonPreferences

from .live_adapter import DEFAULT_SOCKET_PATH

class SketchupAddonPreferences(AddonPreferences):
    bl_idname = __package__

    camera_far_plane: FloatProperty(name="Camera Clip Ends At :", default=250, unit="LENGTH")

    draw_bounds: IntProperty(name="Draw Similar Objects As Bounds When It's Over :", default=1000)
    follow_viewport: BoolProperty(
        name="Follow SketchUp Viewport",
        description="Continuously match the Blender 3D viewport to the SketchUp camera",
        default=True,
    )
    connection_mode: EnumProperty(
        name="Connection Mode",
        description="Transport mode for connecting to SketchUp",
        items=(
            ('UNIX', 'Unix Socket', 'Connect via Unix domain socket'),
            ('TCP', 'TCP/IP', 'Connect via TCP/IP'),
        ),
        default='UNIX',
    )
    socket_path: StringProperty(
        name="Socket Path",
        description="Unix socket path for live sync connection",
        default=DEFAULT_SOCKET_PATH,
        subtype='FILE_PATH',
    )
    tcp_host: StringProperty(
        name="TCP Host",
        description="TCP host for live sync connection",
        default='127.0.0.1',
    )
    tcp_port: IntProperty(
        name="TCP Port",
        description="TCP port for live sync connection",
        default=9876,
        min=1,
        max=65535,
    )
    binary_textures: BoolProperty(
        name="Binary Textures",
        description="Fetch textures as binary via TCP endpoint (reduces transfer size)",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="- Basic Import Options -")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "camera_far_plane")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "draw_bounds")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "follow_viewport")

        layout.separator()
        layout.label(text="- Connection Settings -")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "connection_mode")
        if self.connection_mode == 'UNIX':
            row = layout.row()
            row.use_property_split = True
            row.prop(self, "socket_path")
        else:
            row = layout.row()
            row.use_property_split = True
            row.prop(self, "tcp_host")
            row = layout.row()
            row.use_property_split = True
            row.prop(self, "tcp_port")
            row = layout.row()
            row.use_property_split = True
            row.prop(self, "binary_textures")