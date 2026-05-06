"""
SketchUp Link & Importer — combined Blender addon package.

Exposes the unified register() / unregister() entry points that Blender
calls when the addon is enabled/disabled.
"""

import bpy

from .live_sync import (
    SKETCHUP_PT_LiveSync,
    SKETCHUP_PT_RenderSettings,
    SketchUpStartLiveSync,
    SketchUpStopLiveSync,
    SketchUpQuickRender,
    SketchUpQuickRenderViewport,
)
from .preferences import SketchupAddonPreferences
from .scene_importer import ExportSKP, ImportSKP, LiveImportSKP, menu_func_export, menu_func_import, menu_func_live_import


def register():
    """Register all operators, panels, preferences, and menu items."""
    bpy.utils.register_class(SketchupAddonPreferences)
    bpy.utils.register_class(ImportSKP)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.utils.register_class(LiveImportSKP)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_live_import)
    bpy.utils.register_class(ExportSKP)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
    bpy.utils.register_class(SketchUpStartLiveSync)
    bpy.utils.register_class(SketchUpStopLiveSync)
    bpy.utils.register_class(SKETCHUP_PT_LiveSync)
    bpy.utils.register_class(SketchUpQuickRender)
    bpy.utils.register_class(SketchUpQuickRenderViewport)
    bpy.utils.register_class(SKETCHUP_PT_RenderSettings)


def unregister():
    """Unregister all operators, panels, preferences, and menu items."""
    # Stop live sync if running
    from .live_sync import _sync_state

    if _sync_state["running"]:
        _sync_state["running"] = False
        if _sync_state["stop_event"]:
            _sync_state["stop_event"].set()

    bpy.utils.unregister_class(SketchUpQuickRender)
    bpy.utils.unregister_class(SketchUpQuickRenderViewport)
    bpy.utils.unregister_class(SKETCHUP_PT_RenderSettings)
    bpy.utils.unregister_class(ImportSKP)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(LiveImportSKP)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_live_import)
    bpy.utils.unregister_class(ExportSKP)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.utils.unregister_class(SketchUpStartLiveSync)
    bpy.utils.unregister_class(SketchUpStopLiveSync)
    bpy.utils.unregister_class(SKETCHUP_PT_LiveSync)
    bpy.utils.unregister_class(SketchupAddonPreferences)
