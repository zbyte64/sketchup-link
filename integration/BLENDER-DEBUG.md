# Blender verification containers

Debug layer on the Blender test images (`Dockerfile.blender-debug`), for inspecting the
Blender GUI and driving Blender from outside the container.

## Services

| Service | Port | Notes |
|---|---|---|
| sshd | 22 (host 2231 for 4.5, 2232 for 5.2) | Key-only. Uses `integration/oem/authorized_keys.pub`. Password login is refused. |
| Xvfb | display `:99` | Virtual display; Blender's GUI runs on it. |
| x11vnc | 5900 | VNC view of `:99`. |
| MCP for Blender | 9876 (inside container) | Community add-on, started through `blendermcp.start_server`. |

## Port conflict

The MCP add-on defaults to port **9876**, the same as `sketchup_link`. They must not run
in the same container. The SketchUp side uses the VM, so this only matters if both are run
against one host network namespace.

## Verified

- Key login works on both containers (4.5.16 and 5.2.4); password login is refused.
- Blender GUI renders on `:99` and a screenshot shows the full interface.
- The MCP add-on starts through its own operator and answers a `get_scene_info` request
  with the scene (Cube, Light, Camera).

## Not verified

- The add-on on Blender 5.2 (only 4.5 has been run).
- Driving the add-on's tool set beyond `get_scene_info`.
