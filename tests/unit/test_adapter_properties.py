"""Property tests for adapter invariants in blender_plugin/live_adapter.py."""
from __future__ import annotations

from hypothesis import assume, given, strategies as st

from blender_plugin.live_adapter import JsonEntities, JsonFace, JsonInstance, JsonLayer, _JsonColor, _flat_to_4x4

_finite_floats = st.floats(allow_nan=False, allow_infinity=False)
_layer_names = st.text(min_size=1)


@given(st.lists(_finite_floats, min_size=16, max_size=16))
def test_flat_to_4x4_preserves_row_major_order(flat):
    matrix = _flat_to_4x4(flat)
    assert len(matrix) == 4
    assert all(len(row) == 4 for row in matrix)
    assert [v for row in matrix for v in row] == flat


def test_flat_to_4x4_none_is_identity():
    assert _flat_to_4x4(None) == [
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1],
    ]


def test_json_color_unpacks_rgba_in_order():
    r, g, b, a = _JsonColor({"r": 10, "g": 20, "b": 30, "a": 40})
    assert (r, g, b, a) == (10, 20, 30, 40)


def test_json_color_defaults_to_opaque_black():
    assert tuple(_JsonColor({})) == (0, 0, 0, 255)


@given(name=_layer_names, visible_a=st.booleans(), visible_b=st.booleans())
def test_layers_with_same_name_are_equal_and_hash_alike(name, visible_a, visible_b):
    a = JsonLayer({"name": name, "visible": visible_a})
    b = JsonLayer({"name": name, "visible": visible_b})
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1


@given(name_a=_layer_names, name_b=_layer_names)
def test_layers_with_different_names_are_not_equal(name_a, name_b):
    assume(name_a != name_b)
    assert JsonLayer({"name": name_a}) != JsonLayer({"name": name_b})


def test_face_back_uvs_absent_is_none():
    assert JsonFace({"uvs": [[0, 0]]}).back_uvs is None


def test_face_back_uvs_are_tuples_in_point_order():
    assert JsonFace({"back_uvs": [[0.5, 1.0], [2, 3]]}).back_uvs == [(0.5, 1.0), (2, 3)]


def _square_face(pid, z=0.0):
    return {
        "type": "Face", "persistent_id": pid,
        "outer_loop": [{"x": 0, "y": 0, "z": z}, {"x": 1, "y": 0, "z": z},
                       {"x": 1, "y": 1, "z": z}, {"x": 0, "y": 1, "z": z}],
    }


def _edge(a, b, smooth):
    return {"type": "Edge", "persistent_id": 0, "vertices": [a, b], "smooth": smooth, "soft": smooth,
            "hidden": False}


def _smooth_flags(entities):
    """GetSmooth() of each face in a JsonEntities list, by persistent id."""
    return {f.persistent_id: any(e.GetSmooth() for e in f.edges) for f in JsonEntities(entities).faces}


def test_face_on_a_smooth_edge_reports_smooth():
    """A smooth edge on a face's boundary makes the face smooth, as SketchUp's own shading does."""
    square = _square_face(1)
    smooth = _edge([1, 0, 0], [1, 1, 0], True)
    assert _smooth_flags([square, smooth]) == {1: True}


def test_face_with_no_smooth_edge_stays_flat():
    square = _square_face(2)
    flat = _edge([1, 0, 0], [1, 1, 0], False)
    assert _smooth_flags([square, flat]) == {2: False}


def test_smooth_edge_off_the_boundary_does_not_smooth_the_face():
    """An edge that is not on this face's boundary must not change its shading."""
    square = _square_face(3)
    elsewhere = _edge([5, 5, 0], [6, 5, 0], True)
    assert _smooth_flags([square, elsewhere]) == {3: False}


def test_attaching_edges_does_not_rescan_every_edge_per_face():
    """Attaching boundary edges to N faces must not normalise every edge's endpoints once per face.

    A 64x64 grid has 4096 faces and about 8320 edges. Normalising each edge once per face is ~34M
    point conversions and took minutes in Blender; the edge endpoints must be normalised once.
    The count is of work done, not wall-clock time, so the test is deterministic.
    """
    import blender_plugin.live_adapter as la

    calls = {"n": 0}

    faces, edges = [], []
    n = 16
    for i in range(n):
        for j in range(n):
            x, y = i * 1.0, j * 1.0
            loop = [{"x": x, "y": y, "z": 0}, {"x": x + 1, "y": y, "z": 0},
                    {"x": x + 1, "y": y + 1, "z": 0}, {"x": x, "y": y + 1, "z": 0}]
            faces.append({"type": "Face", "persistent_id": len(faces) + 1, "outer_loop": loop})
            for a, b in [((x, y, 0), (x + 1, y, 0)), ((x + 1, y, 0), (x + 1, y + 1, 0))]:
                edges.append({"type": "Edge", "vertices": [list(a), list(b)], "smooth": True})
    snapshot = faces + edges

    # Count endpoint reads by wrapping each edge so every access to its vertices is counted.
    class CountingEdge(dict):
        def get(self, k, d=None):
            if k == "vertices":
                calls["n"] += 1
            return super().get(k, d)

    counted = [CountingEdge(e) for e in edges]
    la.JsonEntities(faces + counted).faces
    per_face_scans = calls["n"]
    assert per_face_scans <= len(edges) + 2 * len(faces), (
        f"each face rescans every edge: {per_face_scans} endpoint reads for {len(faces)} faces and {len(edges)} edges"
    )


def test_nested_instance_definition_exposes_its_entities():
    """A component instance inside another component must resolve its definition to real entities.

    The depth analysis recurses through instance.definition.entities. The instance's definition used to be a
    name-only stub with no entities, so any component containing a component instance failed to import:
    'AttributeError: _NameOnly has no attribute entities', rejecting the whole live sync.
    """
    defs = {
        "Leaf": {"name": "Leaf", "entities": [{"type": "Face", "persistent_id": 9, "outer_loop": []}]},
        "Mid": {"name": "Mid", "entities": [{"type": "ComponentInstance", "definition_name": "Leaf",
                                             "transformation": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}]},
    }
    inst = JsonInstance({"type": "ComponentInstance", "definition_name": "Leaf"}, definitions=defs)
    assert hasattr(inst.definition, "entities")
    assert [f.persistent_id for f in JsonEntities(inst.definition.entities).faces] == [9]


def test_instance_with_missing_definition_is_skipped_not_crashing():
    """A component instance whose definition is absent from the snapshot must not poison the depth analysis.

    An instance returning a name-only stub with no entities makes component_deps raise AttributeError and
    reject the whole live sync. Such an instance is malformed (the serializer emits every definition it
    references), so it is skipped as an instance, not allowed to crash the import.
    """
    from blender_plugin.live_adapter import JsonEntities
    ghost = {"type": "ComponentInstance", "definition_name": "Ghost",
             "transformation": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}
    ents = JsonEntities([ghost], definitions={})
    # Skipped: no instance is offered for the depth analysis to recurse into.
    assert ents.instances == []
