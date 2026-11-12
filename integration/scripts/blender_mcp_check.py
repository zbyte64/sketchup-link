"""Start the MCP for Blender add-on through its own operator and read a scene reply.

Run inside a debug container (Blender GUI on :99):

    blender --factory-startup --python integration/scripts/blender_mcp_check.py

Expects the add-on at /tmp/mcp_addon.py (copied in from ahujasid/mcp-for-blender).
Prints MCPDBG lines; the direct socket request in the shell is the authoritative reply.
"""
import bpy
import importlib.util


def _start():
    spec = importlib.util.spec_from_file_location("mcp_addon", "/tmp/mcp_addon.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.register()
    bpy.context.scene.blendermcp_port = 9876
    result = bpy.ops.blendermcp.start_server()
    print("MCPDBG operator result:", result, flush=True)
    return None


bpy.app.timers.register(_start, first_interval=8.0)
