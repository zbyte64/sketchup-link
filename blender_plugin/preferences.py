"""SketchUp Addon Preferences — extracted from the original scene_importer."""

import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty
from bpy.types import AddonPreferences


class SketchupAddonPreferences(AddonPreferences):
    bl_idname = __package__

    camera_far_plane: FloatProperty(name="Camera Clip Ends At :", default=250, unit="LENGTH")

    draw_bounds: IntProperty(name="Draw Similar Objects As Bounds When It's Over :", default=1000)
    follow_viewport: BoolProperty(
        name="Follow SketchUp Viewport",
        description="Continuously match the Blender 3D viewport to the SketchUp camera",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="- Basic Import Options -")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "camera_far_plane")
        layout = self.layout
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "draw_bounds")
