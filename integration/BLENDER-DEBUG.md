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

## Visual checks: live sync

Verified on Blender 4.5.16 and 5.2.4 (captured from the GUI session on :99):

- The SketchUp Link panel registers, and a live import produces the `SKP Imported Data`
  hierarchy in the outliner with the imported chair and loose-entity geometry visible.
- The live import no longer deletes `/tmp` (fixed in 3708ad3; regression test added).

### Material colour: data verified, visual not shown

- SketchUp `Blue` changed to `(220,40,40)` and the sync carries it: the Blender material's
  Principled base colour reads `(0.723, 0.017, 0.017)` linear, which is that colour.
- The change is **not visible** in the captures. The only Blender object using `Blue` is a
  single polygon (`_(Loose Entity)` polygon 7) inside a large `DefaultMaterial` mesh, so at
  any framing the red is a few pixels or hidden. A before/after pair of captures therefore
  shows no difference, which is the honest result, not a pass.
- To visually verify a material change, the material must be on a whole object that can be
  framed, for example a component instance whose faces all use the changed material.

### Capture notes

- Screen captures are identical when nothing redraws, so compare hashes before claiming a
  change. A capture hash equal to the previous capture means no visible change.
- Edit Mode leaks in from framing scripts; set `object.mode_set(mode="OBJECT")` first.
