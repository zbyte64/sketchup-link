"""Property tests for adapter invariants in blender_plugin/live_adapter.py."""
from __future__ import annotations

from hypothesis import assume, given, strategies as st

from blender_plugin.live_adapter import JsonFace, JsonLayer, _JsonColor, _flat_to_4x4

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
