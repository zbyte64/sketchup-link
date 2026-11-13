# Bidirectional geometry editing: design (milestone 2)

Status: **accepted for implementation**. Builds on milestone 1
(`blender-to-sketchup-sync.md`), which settled the conflict policy (SketchUp wins with a
visible warning) and the identity map (`skp_persistent_id`).

## Scope

Milestone 2 lets Blender **add** and **delete** faces that originated in SketchUp, and
add new faces created in Blender, so that geometry edits made in Blender reach SketchUp.
Milestone 1's transform and material sync continues to apply.

Out of scope for this milestone: editing vertices or edges of an existing face in place.
Moving a vertex is expressed as delete-and-re-add, which is the simplest faithful model
and avoids a separate vertex-identity map.

## Verified facts this design rests on

Checked against the live SketchUp 2025 model, not assumed.

| Fact | Evidence |
|---|---|
| Add-face returns the new face's id | `POST /control/geometry/face` returned `{"ok":true,"persistent_id":43827}`, and that id is in the next snapshot |
| Delete-by-id removes the face | `POST /control/geometry/delete` returned 200 and the face left the snapshot |
| Snapshot faces carry the full boundary | Each face has `outer_loop` and `loops` (boundary plus holes), not only triangles |
| Holes are common in the live model | 21 of 193 faces have more than one loop (up to 8) |

## Decisions

### 1. Mesh-to-face conversion uses loops, not triangles

A Blender mesh is converted to SketchUp faces polygon by polygon, using each polygon's
vertex loop. Triangulated input would make every SketchUp face a triangle and destroy the
original face structure. We do not reconstruct holes from triangles: a Blender face that
has an inner boundary is represented as its outer loop plus inner loops, where the mesh
provides them. Where Blender cannot express a hole (plain polygons), the face is created
as its outer loop only and the limitation is reported, never silently dropped.

### 2. New faces are added through the control route and get identities from SketchUp

A Blender-created face has no SketchUp id until it is added. The push adds it through
`/control/geometry/face`, takes the returned `persistent_id`, and writes it onto the
Blender polygon's object as the new identity. Until that write, the face is not tracked.

### 3. Deleting in Blender deletes in SketchUp, under the same conflict policy

A tagged object removed in Blender is a delete edit. It is pushed through
`/control/geometry/delete` only if SketchUp still matches the last-synced state. If
SketchUp changed the object since the last sync, SketchUp wins: the object is restored
on the next import and a warning is shown, as milestone 1 does for transforms.

### 4. Edits are pushed in dependency order

Adds before deletes within one poll, so a replaced face (delete plus add) never leaves a
gap. Each push reads SketchUp's current state first, as in milestone 1.

### 5. Echo suppression extends to adds and deletes

A pushed add reappears in the next snapshot with the id we just recorded. The importer
must not treat that as a new Blender object to push again. The last-synced set (ids the
sides agree on) provides this, the same mechanism as milestone 1's baseline.

## Risks

- **Holes cannot always be reconstructed from a plain Blender mesh.** Mitigated by decision
  1: the limitation is reported, not hidden. This is the main known lossy case.
- **Face orientation.** SketchUp faces have a front and back; Blender polygons have a
  normal. A reversed normal produces a face with the wrong front material. The push must
  orient the face to the Blender normal.
- **Replace vs. edit.** Editing a vertex is modelled as delete and re-add, which changes
  the face's SketchUp id. Anything keyed on the old id (materials applied per face,
  references in other tooling) loses that link. Documented as a consequence.
- **Large pushes.** A dense mesh edit can produce many control calls per poll. Batched
  per poll, with failures reported per face, not all-or-nothing.

## Limitations (as built)

These are measured failures or unbuilt parts, recorded so the doc does not claim more than the code does.

1. **Concave faces cannot be reshaped faithfully.** The boundary walk recovers a concave face's true outline,
   verified on a U-shaped face. But SketchUp's `add_face`, given that loop in any order, stores a self-intersecting
   polygon with the same vertices and area and the wrong boundary (10 edges differ). Drawing the boundary as edges
   forms no face. The live check `live_timer_concave_check` fails on this and is kept as the record. Options not yet
   decided: split a concave face into convex pieces SketchUp builds correctly, or refuse concave reshapes and keep
   them as warned, Blender-only edits. The current code does not refuse them; it pushes the wrong outline. This is
   the most important open defect and should be closed before the reshape route is relied on for concave geometry.

2. **Top-level loose faces are not reshaped.** A face not inside a group or component is imported into
   `_(Loose Entity)`, which carries no SketchUp identity, and the timer only pushes identified objects. Edits to
   loose top-level geometry are therefore not pushed.

3. **Faces with holes are refused.** A face with an inner loop has two boundary loops, so no single outline can be
   walked. The timer does not push such a face and reports it.

4. **Idle-pass cost is unmeasured.** The imported-geometry check runs on every timer pass, including passes with no new
   snapshot. Its cost under a sustained poll loop has not been measured.

5. **Only the reference geometry is exercised for reshape.** Multi-face edits, edits that add polygons to an imported
   object, and vertex edits that move a face out of its plane are untested.

## Test plan

- Unit: loop-based conversion (outer only, with holes, and a polygon that cannot express
  a hole is reported); orientation follows the Blender normal; echo suppression for adds
  and deletes; dependency ordering (adds before deletes).
- Live (VM, Blender 4.5 and 5.2): add a face in Blender, push, verify SketchUp has a face
  with the returned id; delete a tagged face in Blender, push, verify it is gone; a
  delete that conflicts with a SketchUp change is restored and warned; an add reappears in
  the snapshot without being re-pushed.
- Regression: milestone 1 live checks and the existing live import and delete checks stay
  green.

## Open questions (none blocking)

1. Whether to expose the hole limitation as a per-face warning or only as a summary. The
   design reports per face; a summary can be added later if the list gets long.
