"""
tests/integration/test_live_adapter.py

Integration tests for sketchup_link.live_adapter.

The Ruby mock server (server.rb) generates a structurally fixed but value-
randomized model snapshot from Factories.test_model:

  Top-level entities (5):
    [0] Face  — material='Red', no back_material
    [1] Face  — back_material='Blue', no material
    [2] Edge  — no material
    [3] Group — name='FurnitureGroup', layer='Furniture', identity transform
                 entities: [Face, Edge]
    [4] ComponentInstance — definition_name='Chair', layer='Furniture'

  Materials (2): Red(r=220,g=20,b=20,a=255) and Blue(r=20,g=20,b=200,a=255)
  Layers (3):    Layer0(visible=True), Furniture(visible=True), Hidden(visible=False)
  Definitions:   'Chair' — num_instances=1, num_used_instances=1, entities=[Face, Face]

All fixtures are session-scoped (conftest.py): the Ruby server starts once,
model JSON is fetched once, and JsonModel is constructed once.
"""

import pytest


# ===========================================================================
# Transport — fetch_model_json
# ===========================================================================

class TestTransport:
    def test_fetch_model_json_returns_dict(self, ruby_server):
        from sketchup_link.live_adapter import fetch_model_json
        data = fetch_model_json(ruby_server)
        assert isinstance(data, dict)

    def test_fetch_model_json_has_required_keys(self, ruby_server):
        from sketchup_link.live_adapter import fetch_model_json
        data = fetch_model_json(ruby_server)
        for key in ('model_guid', 'title', 'entities', 'materials', 'layers',
                    'component_definitions'):
            assert key in data, f"Missing top-level key: {key!r}"

    def test_fetch_model_json_title(self, model_data):
        assert model_data['title'] == 'Integration Test Model'

    def test_fetch_model_json_raises_on_bad_path(self):
        from sketchup_link.live_adapter import fetch_model_json
        import socket
        with pytest.raises((OSError, ConnectionRefusedError, FileNotFoundError)):
            fetch_model_json('/tmp/sketchup-link-nonexistent.sock')


# ===========================================================================
# JsonModel — top-level model properties
# ===========================================================================

class TestJsonModel:
    def test_scenes_is_empty_list(self, json_model):
        assert json_model.scenes == []

    def test_camera_fov(self, json_model):
        assert json_model.camera.fov == 35.0

    def test_camera_aspect_ratio_is_false(self, json_model):
        assert json_model.camera.aspect_ratio is False

    def test_camera_get_orientation_returns_three_values(self, json_model):
        result = json_model.camera.GetOrientation()
        assert len(result) == 3

    def test_materials_count(self, json_model):
        assert len(json_model.materials) == 2

    def test_layers_count(self, json_model):
        assert len(json_model.layers) == 3


# ===========================================================================
# JsonEntities — top-level entity filtering
# ===========================================================================

class TestJsonEntities:
    def test_top_level_faces_count(self, json_model):
        assert len(json_model.entities.faces) == 2

    def test_top_level_groups_count(self, json_model):
        assert len(json_model.entities.groups) == 1

    def test_top_level_instances_count(self, json_model):
        assert len(json_model.entities.instances) == 1

    def test_entities_iterable_total_count(self, json_model):
        # face, face, edge, group, instance = 5 items
        items = list(json_model.entities)
        assert len(items) == 5

    def test_entities_types_present(self, json_model):
        types = {item.get('type') for item in json_model.entities}
        assert 'Face' in types
        assert 'Edge' in types
        assert 'Group' in types
        assert 'ComponentInstance' in types


# ===========================================================================
# JsonFace — tessfaces, material, back_material, edges, st_scale
# ===========================================================================

class TestJsonFace:
    @pytest.fixture(scope='class')
    def faces(self, json_model):
        # [0]: material='Red', [1]: back_material='Blue'
        return json_model.entities.faces

    def test_tessfaces_returns_three_tuple(self, faces):
        result = faces[0].tessfaces
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_tessfaces_verts_and_uvs_same_length(self, faces):
        for face in faces:
            verts, tris, uvs = face.tessfaces
            assert len(verts) == len(uvs), (
                f"len(verts)={len(verts)} != len(uvs)={len(uvs)}"
            )

    def test_tessfaces_quad_has_four_verts(self, faces):
        verts, _, _ = faces[0].tessfaces
        assert len(verts) == 4

    def test_tessfaces_quad_has_two_triangles(self, faces):
        _, tris, _ = faces[0].tessfaces
        assert len(tris) == 2

    def test_tessfaces_verts_are_tuples_of_three(self, faces):
        verts, _, _ = faces[0].tessfaces
        for v in verts:
            assert isinstance(v, tuple)
            assert len(v) == 3

    def test_tessfaces_tris_are_tuples_of_three_indices(self, faces):
        _, tris, _ = faces[0].tessfaces
        for t in tris:
            assert isinstance(t, tuple)
            assert len(t) == 3

    def test_tessfaces_triangle_indices_in_bounds(self, faces):
        for face in faces:
            verts, tris, _ = face.tessfaces
            for tri in tris:
                for idx in tri:
                    assert 0 <= idx < len(verts), (
                        f"triangle index {idx} out of range [0, {len(verts)})"
                    )

    def test_tessfaces_uvs_are_tuples_of_two(self, faces):
        _, _, uvs = faces[0].tessfaces
        for u in uvs:
            assert isinstance(u, tuple)
            assert len(u) == 2

    def test_face_with_material_name(self, faces):
        assert faces[0].material is not None
        assert faces[0].material.name == 'Red'

    def test_face_with_material_no_back_material(self, faces):
        assert faces[0].back_material is None

    def test_face_with_back_material_name(self, faces):
        assert faces[1].back_material is not None
        assert faces[1].back_material.name == 'Blue'

    def test_face_with_back_material_no_front_material(self, faces):
        assert faces[1].material is None

    def test_edges_is_empty_list(self, faces):
        for face in faces:
            assert face.edges == []

    def test_st_scale_returns_unit_pair(self, faces):
        assert faces[0].st_scale == (1.0, 1.0)

    def test_st_scale_setter_is_noop(self, faces):
        faces[0].st_scale = (2.0, 3.0)
        assert faces[0].st_scale == (1.0, 1.0)


# ===========================================================================
# JsonGroup — name, layer, transform, nested entities, hidden
# ===========================================================================

class TestJsonGroup:
    @pytest.fixture(scope='class')
    def group(self, json_model):
        return json_model.entities.groups[0]

    def test_group_name(self, group):
        assert group.name == 'FurnitureGroup'

    def test_group_layer_name(self, group):
        assert group.layer is not None
        assert group.layer.name == 'Furniture'

    def test_group_transform_is_4x4(self, group):
        t = group.transform
        assert len(t) == 4
        assert all(len(row) == 4 for row in t)

    def test_group_identity_transform_diagonal(self, group):
        t = group.transform
        assert t[0][0] == 1
        assert t[1][1] == 1
        assert t[2][2] == 1
        assert t[3][3] == 1

    def test_group_identity_transform_off_diagonal_zero(self, group):
        t = group.transform
        assert t[0][1] == 0
        assert t[0][2] == 0
        assert t[1][0] == 0
        assert t[2][0] == 0

    def test_group_entities_has_one_face(self, group):
        assert len(group.entities.faces) == 1

    def test_group_entities_raw_list_has_edge(self, group):
        types = [item.get('type') for item in group.entities]
        assert 'Edge' in types

    def test_group_nested_face_tessfaces_invariant(self, group):
        nested_face = group.entities.faces[0]
        verts, tris, uvs = nested_face.tessfaces
        assert len(verts) == len(uvs)
        assert len(tris) > 0

    def test_group_hidden_defaults_false(self, group):
        assert group.hidden is False

    def test_group_material_is_none(self, group):
        # Factories.group does not set a material
        assert group.material is None


# ===========================================================================
# JsonInstance — definition name, layer, transform, hidden
# ===========================================================================

class TestJsonInstance:
    @pytest.fixture(scope='class')
    def instance(self, json_model):
        return json_model.entities.instances[0]

    def test_instance_definition_name(self, instance):
        assert instance.definition.name == 'Chair'

    def test_instance_layer_name(self, instance):
        assert instance.layer is not None
        assert instance.layer.name == 'Furniture'

    def test_instance_transform_is_4x4(self, instance):
        t = instance.transform
        assert len(t) == 4
        assert all(len(row) == 4 for row in t)

    def test_instance_identity_transform(self, instance):
        t = instance.transform
        assert t[0][0] == 1
        assert t[1][1] == 1
        assert t[2][2] == 1
        assert t[3][3] == 1

    def test_instance_hidden_defaults_false(self, instance):
        assert instance.hidden is False

    def test_instance_material_is_none(self, instance):
        assert instance.material is None


# ===========================================================================
# JsonMaterial — name, color channels, opacity, texture
# ===========================================================================

class TestJsonMaterial:
    @pytest.fixture(scope='class')
    def by_name(self, json_model):
        return {m.name: m for m in json_model.materials}

    def test_red_material_present(self, by_name):
        assert 'Red' in by_name

    def test_blue_material_present(self, by_name):
        assert 'Blue' in by_name

    def test_red_color_r(self, by_name):
        r, g, b, a = by_name['Red'].color
        assert r == 220

    def test_red_color_g(self, by_name):
        r, g, b, a = by_name['Red'].color
        assert g == 20

    def test_red_color_b(self, by_name):
        r, g, b, a = by_name['Red'].color
        assert b == 20

    def test_red_color_a(self, by_name):
        r, g, b, a = by_name['Red'].color
        assert a == 255

    def test_blue_color_channels(self, by_name):
        r, g, b, a = by_name['Blue'].color
        assert r == 20
        assert g == 20
        assert b == 200
        assert a == 255

    def test_color_is_iterable_four_values(self, by_name):
        channels = list(by_name['Red'].color)
        assert len(channels) == 4

    def test_red_opacity(self, by_name):
        assert by_name['Red'].opacity == 1.0

    def test_texture_is_none_for_live_import(self, by_name):
        assert by_name['Red'].texture is None
        assert by_name['Blue'].texture is None


# ===========================================================================
# JsonLayer — name, visible, __eq__, __hash__
# ===========================================================================

class TestJsonLayer:
    @pytest.fixture(scope='class')
    def by_name(self, json_model):
        return {l.name: l for l in json_model.layers}

    def test_layer0_visible(self, by_name):
        assert by_name['Layer0'].visible is True

    def test_furniture_visible(self, by_name):
        assert by_name['Furniture'].visible is True

    def test_hidden_not_visible(self, by_name):
        assert by_name['Hidden'].visible is False

    def test_layer_equality_same_name_different_visible(self):
        from sketchup_link.live_adapter import JsonLayer
        l1 = JsonLayer({'name': 'Layer0', 'visible': True})
        l2 = JsonLayer({'name': 'Layer0', 'visible': False})
        assert l1 == l2

    def test_layer_inequality_different_name(self):
        from sketchup_link.live_adapter import JsonLayer
        l1 = JsonLayer({'name': 'Layer0',    'visible': True})
        l2 = JsonLayer({'name': 'Furniture', 'visible': True})
        assert l1 != l2

    def test_layer_hash_same_for_same_name(self):
        from sketchup_link.live_adapter import JsonLayer
        l1 = JsonLayer({'name': 'Layer0', 'visible': True})
        l2 = JsonLayer({'name': 'Layer0', 'visible': False})
        assert hash(l1) == hash(l2)

    def test_layers_usable_in_set_deduplication(self):
        from sketchup_link.live_adapter import JsonLayer
        l1 = JsonLayer({'name': 'Layer0', 'visible': True})
        l2 = JsonLayer({'name': 'Layer0', 'visible': False})
        assert len({l1, l2}) == 1

    def test_layers_in_set_different_names(self):
        from sketchup_link.live_adapter import JsonLayer
        layers = [
            JsonLayer({'name': 'A', 'visible': True}),
            JsonLayer({'name': 'B', 'visible': True}),
            JsonLayer({'name': 'A', 'visible': False}),  # duplicate of first
        ]
        assert len(set(layers)) == 2


# ===========================================================================
# JsonDefinitionRef — name, numInstances, numUsedInstances, entities
# ===========================================================================

class TestJsonDefinitionRef:
    @pytest.fixture(scope='class')
    def chair(self, json_model):
        return json_model.component_definition_as_dict['Chair']

    def test_definition_name(self, chair):
        assert chair.name == 'Chair'

    def test_num_instances(self, chair):
        assert chair.numInstances == 1

    def test_num_used_instances(self, chair):
        assert chair.numUsedInstances == 1

    def test_entities_has_two_faces(self, chair):
        assert len(chair.entities.faces) == 2

    def test_definition_faces_tessfaces_invariant(self, chair):
        for face in chair.entities.faces:
            verts, tris, uvs = face.tessfaces
            assert len(verts) == len(uvs)
            assert len(tris) > 0


# ===========================================================================
# component_definition_as_dict and component_definitions (iterable)
# ===========================================================================

class TestComponentDefinitions:
    def test_component_definition_as_dict_has_chair(self, json_model):
        d = json_model.component_definition_as_dict
        assert 'Chair' in d

    def test_component_definitions_iterable_length(self, json_model):
        defs = list(json_model.component_definitions)
        assert len(defs) == 1

    def test_component_definitions_iterable_returns_def_refs(self, json_model):
        from sketchup_link.live_adapter import JsonDefinitionRef
        defs = list(json_model.component_definitions)
        assert all(isinstance(d, JsonDefinitionRef) for d in defs)

    def test_component_definitions_iterable_name(self, json_model):
        defs = list(json_model.component_definitions)
        assert defs[0].name == 'Chair'
