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

    # === Feature 1: Shadow/Sun ===
    import_sun_light: BoolProperty(
        name="Import Sun Light",
        description="Create a Blender Sun light from SketchUp shadow info",
        default=True,
    )
    setup_world_sky: BoolProperty(
        name="Setup World Sky",
        description="Set up Nishita sky texture from SketchUp shadow info",
        default=True,
    )

    # === Feature 2/3: Render Settings ===
    render_engine: EnumProperty(
        name="Render Engine",
        description="Render engine for Quick Render",
        items=(
            ('CYCLES', 'Cycles', ''),
            ('BLENDER_EEVEE_NEXT', 'Eevee Next', ''),
            ('BLENDER_WORKBENCH', 'Workbench', ''),
        ),
        default='CYCLES',
    )
    render_samples: IntProperty(
        name="Render Samples",
        default=128,
        min=1,
        max=4096,
    )
    render_denoise: BoolProperty(
        name="Denoise",
        description="Enable denoising for Quick Render",
        default=True,
    )
    render_resolution_x: IntProperty(
        name="Resolution X",
        default=1920,
        min=64,
        max=16384,
    )
    render_resolution_y: IntProperty(
        name="Resolution Y",
        default=1080,
        min=64,
        max=16384,
    )
    render_output_dir: StringProperty(
        name="Output Directory",
        description="Directory for Quick Render output images",
        default="//",
        subtype='DIR_PATH',
    )
    render_file_format: EnumProperty(
        name="File Format",
        description="File format for Quick Render output",
        items=(
            ('PNG', 'PNG', ''),
            ('JPEG', 'JPEG', ''),
            ('OPEN_EXR', 'OpenEXR', ''),
        ),
        default='PNG',
    )

    # === Feature 4: World ===
    world_strength: FloatProperty(
        name="World Strength",
        description="Background shader strength",
        default=1.0,
        min=0.0,
        max=10.0,
    )
    world_sky_model: EnumProperty(
        name="Sky Model",
        description="World sky model type",
        items=(
            ('NISHITA', 'Nishita Sky', ''),
            ('FLAT', 'Flat Color', ''),
        ),
        default='NISHITA',
    )

    # === Feature 5: Material Enhancement ===
    enhance_materials: BoolProperty(
        name="Enhance Materials",
        description="Detect and apply companion textures (roughness, normal, etc.)",
        default=True,
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
 
        layout.separator()
        layout.label(text="- Lighting & World -")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "import_sun_light")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "setup_world_sky")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "world_strength")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "world_sky_model")
 
        layout.separator()
        layout.label(text="- Render Settings -")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "render_engine")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "render_samples")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "render_denoise")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "render_resolution_x")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "render_resolution_y")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "render_output_dir")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "render_file_format")
 
        layout.separator()
        layout.label(text="- Material Enhancement -")
        row = layout.row()
        row.use_property_split = True
        row.prop(self, "enhance_materials")