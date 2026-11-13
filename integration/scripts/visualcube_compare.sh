#!/usr/bin/env bash
# Decide whether a SketchUp material change reached the screen on VisualCube.
#
# Inputs: two PNG captures of the same framed viewport, before and after the change.
#
# The cube's own pixels are selected in the BEFORE frame by colour (near the cube's starting colour), and
# the same pixels are read in the AFTER frame. A pass needs most of the cube's area to have changed colour,
# not the average of one window: a single window can sit on the grid, the gizmo or the background, and a
# partial change inside it averages out. The fraction is reported so a partial change is visible.
#
# Exit 0 = the cube changed (fraction >= MIN_FRACTION), 1 = it did not, 2 = usage or capture error.
set -euo pipefail
BEFORE="${1:?before.png}"
AFTER="${2:?after.png}"
# The cube's starting colour (VisualCube at factory Blue, sRGB 20,68,181 as measured in the viewport).
CUBE_RGB="${CUBE_RGB:-20 68 181}"
CUBE_TOL="${CUBE_TOL:-45}"      # per-channel tolerance for "is this a cube pixel"
MIN_FRACTION="${MIN_FRACTION:-0.5}"   # the share of cube pixels that must change colour
MIN_SHIFT="${MIN_SHIFT:-40}"    # per-channel change that counts as a colour change
SIZE="${SIZE:-480x270}"
MIN_CUBE_PIXELS="${MIN_CUBE_PIXELS:-5000}"         # comparison resolution: fast, and fine enough for a cube this size

raw() { convert "$1" -resize "$SIZE!" -depth 8 rgb:- 2>/dev/null || { echo "capture unreadable: $1" >&2; exit 2; }; }
bytes_b="$(mktemp)"; bytes_a="$(mktemp)"
trap 'rm -f "$bytes_b" "$bytes_a"' EXIT
raw "$BEFORE" > "$bytes_b"
raw "$AFTER" > "$bytes_a"

result="$(python3 - "$bytes_b" "$bytes_a" "$CUBE_RGB" "$CUBE_TOL" "$MIN_SHIFT" "$MIN_CUBE_PIXELS" <<'PY'
import sys
before = open(sys.argv[1], 'rb').read()
after = open(sys.argv[2], 'rb').read()
cube = [int(v) for v in sys.argv[3].split()]
tol = int(sys.argv[4]); shift = int(sys.argv[5])
if len(before) != len(after) or len(before) % 3:
    print("ERROR captures differ in size", file=sys.stderr); sys.exit(2)
cube_px = changed = 0
for i in range(0, len(before), 3):
    b = before[i:i+3]
    if all(abs(b[c] - cube[c]) <= tol for c in range(3)):
        cube_px += 1
        a = after[i:i+3]
        if max(abs(a[c] - b[c]) for c in range(3)) >= shift:
            changed += 1
# A before frame must show the cube at a usable size. Too few cube pixels means the frame does not show the
# starting cube (half drawn, wrong view, or no cube), and a fraction computed from them means nothing.
MIN_CUBE_PIXELS = int(sys.argv[6]) if len(sys.argv) > 6 else 5000
if cube_px < MIN_CUBE_PIXELS:
    print(f"ERROR only {cube_px} cube pixels in the before frame (need at least {MIN_CUBE_PIXELS}): "
          f"the frame does not show the starting cube", file=sys.stderr); sys.exit(2)
# The before frame must be the cube's known starting colour. A frame captured before the viewport finished
# drawing shows the cube in another colour or only partly, and would make a change look like a pass.
import statistics
mean_before = [statistics.fmean(before[i+c] for i in range(0, len(before), 3)
                                if all(abs(before[i+k]-cube[k]) <= tol for k in range(3))) for c in range(3)]
drift = max(abs(mean_before[c] - cube[c]) for c in range(3))
if drift > tol:
    print(f"ERROR before frame cube colour {tuple(round(v) for v in mean_before)} is not the starting colour "
          f"{tuple(cube)} (drift {drift:.0f} > {tol}): the frame may be half drawn", file=sys.stderr); sys.exit(2)
print(f"{cube_px} {changed} {changed / cube_px:.4f}")
PY
)"
read -r cube_px changed fraction <<< "$result"
echo "cube pixels in the before frame: $cube_px"
echo "of those, changed colour in the after frame: $changed (fraction $fraction, need >= $MIN_FRACTION)"
if python3 -c "import sys; sys.exit(0 if float('$fraction') >= float('$MIN_FRACTION') else 1)"; then
    echo "RESULT: cube colour changed (PASS)"
    exit 0
fi
echo "RESULT: cube colour did NOT change enough (FAIL)"
exit 1
