"""
Decide whether VisualCube changed colour between two captures of the same framed viewport. Pure Python, no
dependencies, so it runs under the host python3 and under Blender's bundled Python alike.

The cube's own pixels are selected in the BEFORE frame by colour (near the cube's starting colour), and the same
pixels are read in the AFTER frame. A pass needs most of the cube's area to have changed colour, not the average
of one window: a window can sit on the grid, the gizmo or the background, and a partial change averages out.

    python3 visual_compare.py BEFORE.rgb AFTER.rgb "R G B" TOL SHIFT MIN_CUBE_PIXELS
        prints "cube_px changed fraction"; exit 2 with the reason on stderr when the before frame is unusable.
"""
import statistics
import sys


class UnusableFrame(ValueError):
    """The before frame does not show the starting cube, so no fraction computed from it means anything."""


def cube_change(before, after, cube, tol=45, shift=40, min_cube_pixels=5000):
    """Return (cube_px, changed, fraction) for two equal-size packed RGB byte strings."""
    if len(before) != len(after) or len(before) % 3:
        raise UnusableFrame("captures differ in size")
    cube_px = changed = 0
    sums = [0, 0, 0]
    for i in range(0, len(before), 3):
        b = before[i:i + 3]
        if all(abs(b[c] - cube[c]) <= tol for c in range(3)):
            cube_px += 1
            for c in range(3):
                sums[c] += b[c]
            a = after[i:i + 3]
            if max(abs(a[c] - b[c]) for c in range(3)) >= shift:
                changed += 1
    # Too few cube pixels: the frame is half drawn, the wrong view, or has no cube.
    if cube_px < min_cube_pixels:
        raise UnusableFrame(f"only {cube_px} cube pixels in the before frame (need at least {min_cube_pixels}): "
                            f"the frame does not show the starting cube")
    # The before frame must show the cube's known starting colour; a half-drawn frame would fake a change.
    mean_before = [s / cube_px for s in sums]
    drift = max(abs(mean_before[c] - cube[c]) for c in range(3))
    if drift > tol:
        raise UnusableFrame(f"before frame cube colour {tuple(round(v) for v in mean_before)} is not the starting "
                            f"colour {tuple(cube)} (drift {drift:.0f} > {tol}): the frame may be half drawn")
    return cube_px, changed, changed / cube_px


if __name__ == "__main__":
    before = open(sys.argv[1], "rb").read()
    after = open(sys.argv[2], "rb").read()
    cube = [int(v) for v in sys.argv[3].split()]
    try:
        px, ch, frac = cube_change(before, after, cube, int(sys.argv[4]), int(sys.argv[5]),
                                   int(sys.argv[6]) if len(sys.argv) > 6 else 5000)
    except UnusableFrame as e:
        print(f"ERROR {e}", file=sys.stderr)
        sys.exit(2)
    print(f"{px} {ch} {frac:.4f}")
