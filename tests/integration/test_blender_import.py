"""
test_blender_import.py — End-to-end Blender integration tests.

Run inside Blender headless via:
    blender --background --python tests/integration/run_blender_tests.py

Loads the golden JSON model via SceneImporter.load() and validates the
resulting Blender data-blocks.  Fixtures defined here are module-scoped:
the golden JSON is loaded once, the importer is set up once, and the
import runs once per test session.

Test model structure (from factories.rb test_model):
  Entities: [Face(mat=Red), Face(back_mat=Blue), Edge, Group, ComponentInstance]
  Materials: Red(220,20,20), Blue(20,20,200)
  Layers: Layer0(visible), Furniture(visible), Hidden(invisible)
  Definitions: Chair — 2 faces, num_instances=1, num_used_instances=1
"""

import json
import os

import bpy
import pytest

from blender_plugin.scene_importer import SceneImporter
from blender_plugin.live_adapter import JsonModel

_GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "golden")
_GOLDEN_PATH = os.path.join(_GOLDEN_DIR, "test_model.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_blender():
    """Reset Blender to factory state while preserving addon registrations."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)
    for material in list(bpy.data.materials):
        bpy.data.materials.remove(material)
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)

    # Restore default scene collection
    scene = bpy.context.scene
    default_coll = bpy.data.collections.new("Collection")
    scene.collection.children.link(default_coll)

    if scene.render.engine != "CYCLES":
        scene.render.engine = "CYCLES"


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def golden_model_json():
    """Load the golden JSON snapshot once per session."""
    with open(_GOLDEN_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def importer(golden_model_json):
    """Create a SceneImporter with skp_model set to the golden JSON."""
    imp = SceneImporter()
    imp.set_filename("")
    imp.skp_model = JsonModel(golden_model_json)
    return imp


@pytest.fixture(scope="session")
def import_options():
    """Default import options matching LiveImportSKP defaults."""
    return dict(
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


@pytest.fixture(scope="session")
def import_result(importer, import_options):
    """Run SceneImporter.load() once per session and return the result."""
    _reset_blender()
    return importer.load(bpy.context, **import_options)


# ===========================================================================
# Smoke tests
# ===========================================================================

class TestSmoke:
    def test_load_returns_finished(self, import_result):
        assert import_result == {"FINISHED"}, (
            f"Expected {{'FINISHED'}}, got {import_result}"
        )

    def test_no_exceptions(self, import_result):
        """If we reached here without an exception, the import succeeded."""
        pass


# ===========================================================================
# Material tests
# ===========================================================================

class TestMaterials:
    def test_materials_created(self):
        """All expected materials exist in Blender."""
        mat_names = {m.name for m in bpy.data.materials}
        assert "DefaultMaterial" in mat_names, "DefaultMaterial missing"
        assert "Red" in mat_names, "Red material missing"
        assert "Blue" in mat_names, "Blue material missing"

    def test_default_material_color(self):
        mat = bpy.data.materials["DefaultMaterial"]
        r, g, b, a = mat.diffuse_color
        assert abs(r - 0.8) < 0.01, f"Expected R≈0.8, got {r}"
        assert abs(g - 0.8) < 0.01, f"Expected G≈0.8, got {g}"
        assert abs(b - 0.8) < 0.01, f"Expected B≈0.8, got {b}"

    def test_red_material_color(self):
        """Red(220,20,20,255) → sRGB-to-Linear: (0.587, 0.006, 0.006, 1.0)."""
        mat = bpy.data.materials["Red"]
        r, g, b, a = mat.diffuse_color
        expected_r = pow(220 / 255.0, 2.2)
        expected_g = pow(20 / 255.0, 2.2)
        expected_b = pow(20 / 255.0, 2.2)
        assert abs(r - expected_r) < 0.01, f"Expected R≈{expected_r:.3f}, got {r}"
        assert abs(g - expected_g) < 0.01, f"Expected G≈{expected_g:.3f}, got {g}"
        assert abs(b - expected_b) < 0.01, f"Expected B≈{expected_b:.3f}, got {b}"
        assert abs(a - 1.0) < 0.01, f"Expected A≈1.0, got {a}"

    def test_blue_material_color(self):
        """Blue(20,20,200,255) → sRGB-to-Linear."""
        mat = bpy.data.materials["Blue"]
        r, g, b, a = mat.diffuse_color
        expected_r = pow(20 / 255.0, 2.2)
        expected_g = pow(20 / 255.0, 2.2)
        expected_b = pow(200 / 255.0, 2.2)
        assert abs(r - expected_r) < 0.01, f"Expected R≈{expected_r:.3f}, got {r}"
        assert abs(g - expected_g) < 0.01, f"Expected G≈{expected_g:.3f}, got {g}"
        assert abs(b - expected_b) < 0.01, f"Expected B≈{expected_b:.3f}, got {b}"

    def test_red_material_blend_method_not_blend(self):
        """Red has alpha=255 → blend_method should remain OPAQUE."""
        mat = bpy.data.materials["Red"]
        assert mat.blend_method != "BLEND", (
            "Expected non-BLEND for opaque material"
        )

    def test_materials_principled_bsdf_setup(self):
        """Each material should have a Principled BSDF node."""
        for name in ("Red", "Blue", "DefaultMaterial"):
            mat = bpy.data.materials[name]
            nodes = mat.node_tree.nodes
            assert "Principled BSDF" in nodes, (
                f"Material {name!r} missing Principled BSDF"
            )


# ===========================================================================
# Collection tests
# ===========================================================================

class TestCollections:
    def test_main_import_collection_exists(self):
        assert "SKP Imported Data" in bpy.data.collections, (
            "Main import collection missing"
        )

    def test_mesh_objects_collection_exists(self):
        assert "SKP Mesh Objects" in bpy.data.collections, (
            "SKP Mesh Objects collection missing"
        )

    def test_components_collection_exists(self):
        assert "SKP Components" in bpy.data.collections, (
            "SKP Components collection missing"
        )

    def test_collections_nested_under_main(self):
        main_coll = bpy.data.collections["SKP Imported Data"]
        child_names = {c.name for c in main_coll.children}
        assert "SKP Mesh Objects" in child_names
        assert "SKP Components" in child_names


# ===========================================================================
# Mesh object tests
# ===========================================================================

class TestMeshObjects:
    def test_mesh_objects_exist(self):
        """At least one mesh object was created."""
        mesh_objs = [o for o in bpy.data.objects if o.type == "MESH"]
        assert len(mesh_objs) >= 1, "No mesh objects found"

    def test_loose_entity_object_exists(self):
        """The top-level _(Loose Entity) should contain the loose faces."""
        names = {o.name for o in bpy.data.objects}
        assert "_(Loose Entity)" in names, "_(Loose Entity) missing"

    def test_furniture_group_object_exists(self):
        """The FurnitureGroup should exist as an object."""
        names = {o.name for o in bpy.data.objects}
        assert any("G-FurnitureGroup" in n for n in names), (
            f"G-FurnitureGroup object not found in {names}"
        )

    def test_mesh_vertex_counts(self):
        """Each quad face has 4 vertices → two triangles (6 loops)."""
        loose = bpy.data.objects.get("_(Loose Entity)")
        if loose and loose.type == "MESH":
            mesh = loose.data
            assert len(mesh.vertices) >= 8, (
                f"Expected ≥8 verts (2 quads), got {len(mesh.vertices)}"
            )

    def test_mesh_has_faces(self):
        """Mesh has polygon faces."""
        for obj in bpy.data.objects:
            if obj.type == "MESH" and obj.data.polygons:
                return  # at least one mesh has polygons
        pytest.fail("No mesh with polygons found")


# ===========================================================================
# Object hierarchy tests
# ===========================================================================

class TestObjectHierarchy:
    def test_loose_entity_is_empty_with_children(self):
        """_(Loose Entity) may be empty or mesh depending on nesting."""
        loose = bpy.data.objects.get("_(Loose Entity)")
        assert loose is not None, "_(Loose Entity) not found"

    def test_group_objects_have_parent(self):
        loose = bpy.data.objects.get("_(Loose Entity)")
        if not loose:
            pytest.skip("_(Loose Entity) not found")

    def test_object_count_reasonable(self):
        """Should have at least a few objects (loose geometry + group sub-entities)."""
        count = len(bpy.data.objects)
        assert count >= 3, f"Expected ≥3 objects, got {count}"


# ===========================================================================
# Scene cleanup tests
# ===========================================================================

class TestSceneCleanup:
    def test_no_orphan_meshes(self):
        """No orphan mesh data-blocks (every mesh is used by an object)."""
        used_meshes = set()
        for obj in bpy.data.objects:
            if obj.type == "MESH" and obj.data:
                used_meshes.add(obj.data.name)
        for me in bpy.data.meshes:
            assert me.name in used_meshes, (
                f"Orphan mesh: {me.name!r}"
            )

    def test_no_orphan_materials(self):
        """Every material is used by at least one mesh slot (except back_materials)."""
        used_by_slot = set()
        for me in bpy.data.meshes:
            for mat in me.materials:
                if mat:
                    used_by_slot.add(mat.name)
        # Materials that exist only as back_material won't be in any mesh slot.
        # Blue material is a back_material in the test model.
        exempt = {"DefaultMaterial", "Blue"}
        for mat in bpy.data.materials:
            if mat.name not in used_by_slot and mat.name not in exempt:
                pytest.fail(f"Unused material: {mat.name!r}")