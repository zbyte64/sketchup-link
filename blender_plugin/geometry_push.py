"""
geometry_push.py: turn Blender mesh polygons into SketchUp face requests.

Milestone 2 of the Blender -> SketchUp sync (docs/design/bidirectional-geometry.md).

A Blender polygon is a vertex loop. A SketchUp face is a planar loop plus optional inner
loops (holes). We convert polygons from their loops, never from triangles, so the original
face structure survives the round trip. Pure Python: no bpy import, so it is unit-testable.

Points are metres, matching the control route's contract (`add_face` converts to inches).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FaceRequest:
    """One face to add to SketchUp, in the shape /control/geometry/face accepts."""

    points: list                      # outer loop, [[x,y,z], ...] metres, >= 3 points
    polygon_index: int = -1           # the Blender polygon this came from
    reversed_normal: bool = False     # True when the Blender normal was flipped to match
    limitations: list = field(default_factory=list)  # things the face could not express

    def body(self) -> dict:
        return {"points": self.points}


def _ring_is_valid(points) -> bool:
    """A ring can form a SketchUp face only if it has three distinct points and non-zero area.

    Collinear points (e.g. (0,0,0), (1,0,0), (2,0,0)) pass a distinct-point count but enclose
    no area, and SketchUp cannot form a face from them, so they are rejected here.
    """
    if points is None or len(points) < 3:
        return False
    distinct = {tuple(round(c, 9) for c in p) for p in points}
    if len(distinct) < 3:
        return False
    # Newell's method: the magnitude of the polygon's area vector is zero when it is degenerate.
    nx = ny = nz = 0.0
    n = len(points)
    for i in range(n):
        x1, y1, z1 = points[i]
        x2, y2, z2 = points[(i + 1) % n]
        nx += (y1 - y2) * (z1 + z2)
        ny += (z1 - z2) * (x1 + x2)
        nz += (x1 - x2) * (y1 + y2)
    area_sq = nx * nx + ny * ny + nz * nz
    return area_sq > 1e-18


def polygon_to_face(vertex_coords, loop_indices, polygon_index: int = -1,
                    inner_loops=None) -> FaceRequest | None:
    """Convert one Blender polygon to a FaceRequest, or None if it cannot form a face.

    vertex_coords: sequence of (x, y, z) metres, indexed by vertex index.
    loop_indices:  the polygon's vertex indices, in order.
    inner_loops:   optional list of inner loops (each a list of vertex indices), for holes.
                   Blender polygons do not carry holes, so this is None for ordinary input.
                   When provided, holes are reported as a limitation: the add route creates
                   the outer boundary only, and the request says so rather than hiding it.
    """
    outer = [tuple(float(c) for c in vertex_coords[i]) for i in loop_indices]
    if not _ring_is_valid(outer):
        return None

    limitations = []
    if inner_loops:
        limitations.append(
            f"{len(inner_loops)} inner loop(s) not expressible through the add-face route; "
            "created as outer boundary only"
        )

    return FaceRequest(
        points=[list(p) for p in outer],
        polygon_index=polygon_index,
        limitations=limitations,
    )


def orient_to_normal(face: FaceRequest, blender_normal, sketchup_normal) -> FaceRequest:
    """Flip the face's point order if the SketchUp normal disagrees with the Blender normal.

    SketchUp derives a face's front from its point order (counter-clockwise seen from the
    front). A face whose front faces away from the Blender normal gets the wrong front
    material, so reversing the point order corrects it. Normals are compared by dot
    product; a non-positive dot means the faces point opposite ways.
    """
    dot = sum(a * b for a, b in zip(blender_normal, sketchup_normal))
    if dot < 0:
        face.points = list(reversed(face.points))
        face.reversed_normal = True
    return face


def polygons_to_faces(vertex_coords, polygons) -> list[FaceRequest]:
    """Convert every polygon, dropping any that cannot form a face (reported by count)."""
    faces = []
    for i, loop in enumerate(polygons):
        f = polygon_to_face(vertex_coords, loop, polygon_index=i)
        if f is not None:
            faces.append(f)
    return faces


def order_operations(adds: list, deletes: list) -> list[tuple[str, object]]:
    """Adds before deletes within one poll, so a replaced face never leaves a gap.

    Returns a list of ("add", FaceRequest) and ("delete", persistent_id) in push order.
    """
    return [("add", a) for a in adds] + [("delete", d) for d in deletes]
