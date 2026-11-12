"""Unit tests for Blender polygon to SketchUp face conversion (blender_plugin/geometry_push.py)."""

from blender_plugin.geometry_push import (
    FaceRequest,
    order_operations,
    orient_to_normal,
    polygon_to_face,
    polygons_to_faces,
)

SQUARE = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]


def test_quad_polygon_becomes_face_with_its_four_loop_points():
    f = polygon_to_face(SQUARE, [0, 1, 2, 3], polygon_index=5)
    assert f is not None
    assert f.points == [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]]
    assert f.polygon_index == 5
    assert f.limitations == []


def test_loop_is_used_not_triangles():
    # A quad must stay one face with four points, not be split into two triangles.
    f = polygon_to_face(SQUARE, [0, 1, 2, 3])
    assert len(f.points) == 4


def test_degenerate_polygon_is_dropped():
    collinear = [(0, 0, 0), (1, 0, 0), (2, 0, 0)]
    assert polygon_to_face(collinear, [0, 1, 2]) is None


def test_fewer_than_three_points_is_dropped():
    assert polygon_to_face(SQUARE, [0, 1]) is None


def test_duplicate_points_do_not_make_a_face():
    dup = [(0, 0, 0), (0, 0, 0), (0, 0, 0)]
    assert polygon_to_face(dup, [0, 1, 2]) is None


def test_holes_are_reported_not_hidden():
    f = polygon_to_face(SQUARE, [0, 1, 2, 3], inner_loops=[[0, 1, 2]])
    assert f is not None
    assert len(f.limitations) == 1
    assert "inner loop" in f.limitations[0]


def test_polygons_to_faces_drops_only_the_unformable():
    coords = SQUARE + [(2, 0, 0)]
    polys = [[0, 1, 2, 3], [0, 1, 4]]  # second is collinear: (0,0,0),(1,0,0),(2,0,0), zero area
    faces = polygons_to_faces(coords, polys)
    assert len(faces) == 1
    assert faces[0].polygon_index == 0


def test_orientation_flipped_when_normals_disagree():
    f = FaceRequest(points=[[0, 0, 0], [1, 0, 0], [1, 1, 0]])
    orient_to_normal(f, blender_normal=(0, 0, 1), sketchup_normal=(0, 0, -1))
    assert f.reversed_normal is True
    assert f.points == [[1, 1, 0], [1, 0, 0], [0, 0, 0]]


def test_orientation_kept_when_normals_agree():
    f = FaceRequest(points=[[0, 0, 0], [1, 0, 0], [1, 1, 0]])
    orient_to_normal(f, blender_normal=(0, 0, 1), sketchup_normal=(0, 0, 1))
    assert f.reversed_normal is False
    assert f.points == [[0, 0, 0], [1, 0, 0], [1, 1, 0]]


def test_adds_are_ordered_before_deletes():
    a = FaceRequest(points=[[0, 0, 0], [1, 0, 0], [1, 1, 0]])
    ops = order_operations(adds=[a], deletes=[42])
    assert [kind for kind, _ in ops] == ["add", "delete"]
    assert ops[1][1] == 42


def test_face_body_is_the_add_route_shape():
    f = FaceRequest(points=[[0, 0, 0], [1, 0, 0], [1, 1, 0]])
    assert f.body() == {"points": [[0, 0, 0], [1, 0, 0], [1, 1, 0]]}
