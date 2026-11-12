# Blender → SketchUp sync: design (milestone 1)

Status: **accepted** for milestone 1. Decisions are recorded below; code follows this doc.

## Scope of milestone 1

Transform and material edits on objects that originated in SketchUp. Adds and deletes
from Blender are out of scope; they depend on a faithful mesh round-trip (milestone 2).

## Verified facts this design rests on

These were checked against the live SketchUp 2025 model, not assumed.

| Fact | Evidence |
|---|---|
| `persistent_id` is stable across a transform | `FurnitureGroup` was `42496` before and after a transform, and after restoring it |
| New entities get a fresh, unique id | A new group got `42543`, distinct from existing ids |
| The importer does not record the SketchUp id | `scene_importer.py` tags objects only with `skp_link_import` (an "I created this" marker). No `persistent_id` is stored |
| Transform and material write routes exist | `/control/geometry/transform`, `/control/material` (live-tested) |
| Edits reach subscribers | `transaction.commit` and `materials.change` delivered on `/subscribe` (live-tested) |
| Blender has no change capture | No depsgraph or msgbus handler in `blender_plugin/`; the adapter only issues `GET` |

## Design

### 1. Identity map (required)

Every Blender object created from a SketchUp entity stores that entity's id:

- Object custom property `skp_persistent_id` (int), set by the importer.
- Materials store `skp_material_name` (the SketchUp material name is the key the write
  route uses; SketchUp materials have no persistent id).

The map is rebuilt from these properties on every import, so it survives reloads. It is
not a separate database.

### 2. Capturing Blender edits (required)

Use `bpy.app.handlers.depsgraph_update_post`, filtered to objects that carry
`skp_persistent_id`. On each update, compare the object's transform and material colour
with the last value **the importer or a push wrote**. Only true differences are queued.

Comparing against the last-synced value (not "anything changed") avoids echo loops:
a push that the next poll re-imports must not be pushed again.

### 3. Pushing to SketchUp (required)

Pushes go through the existing control routes (`geometry/transform`, `material`), not
through `eval_ruby`. `eval_ruby` is a test tool and is not the production write path.

Pushes run on the main thread (depsgraph handlers already do), are batched per poll,
and report failures in the Blender UI.

### 4. Conflict policy **[DECIDE]**

If SketchUp and Blender both change an entity between polls:

- **A. SketchUp wins, with a visible warning. [DECIDED]** The Blender edit is
  discarded, as today, but the user is told which objects were overwritten. Smallest
  change; keeps SketchUp as source of truth.
- **B. Last write wins.** Simple, but silently loses whichever side wrote first.
- **C. Blender wins.** Reverses the product's source of truth. Not recommended without a
  product decision.

Recommendation: **A**. It replaces today's silent discard with a warning and changes no
other behaviour.

### 5. Echo suppression

A pushed change comes back in the next snapshot. The importer must treat values it
already expects as no-ops, so a push is not re-queued. The last-synced value (step 2)
provides this.

## Risks

- **Depsgraph fires often.** Filter early (only tagged objects, only transform/material
  changes) and debounce.
- **Material identity by name.** Two materials with the same name would collide. Current
  SketchUp exports avoid this, but it is a constraint to test.
- **Component instances.** An instance's transform is relative to its definition. Pushing
  a transform on an instance must target the instance, not the definition. Needs a test
  with the factory `Chair` instance before shipping.
- **Undo in Blender. [DECIDED: pushed.]** Blender undo that changes a tagged object is a
  real edit to the model, so it is pushed like any other change.

## Test plan (milestone 1)

- Unit: last-synced comparison suppresses echoes; only true differences are queued.
- Live (VM): move an object in Blender, poll, assert `geometry/transform` changed the
  SketchUp group; assert the next snapshot matches Blender and nothing is re-pushed.
- Live: change a material colour in Blender, assert SketchUp's material changed.
- Conflict: edit the same object in both, assert the SketchUp value wins and the warning
  is raised.
- Regression: the existing `live_import_check` and `live_delete_check` stay green.

## Decisions

1. Conflict policy: **A**, SketchUp wins with a visible warning.
2. Blender undo: **pushed** to SketchUp.
3. Scope: milestone 1 is **transform and material**. Full bidirectional geometry editing
   (adds, deletes, mesh changes) is the following milestone.
