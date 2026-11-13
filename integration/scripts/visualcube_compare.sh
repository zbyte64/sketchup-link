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

# The decision lives in visual_compare.py, shared with the in-Blender GUI check.
result="$(python3 "$(dirname "$0")/visual_compare.py" "$bytes_b" "$bytes_a" "$CUBE_RGB" "$CUBE_TOL" "$MIN_SHIFT" "$MIN_CUBE_PIXELS")"
read -r cube_px changed fraction <<< "$result"
echo "cube pixels in the before frame: $cube_px"
echo "of those, changed colour in the after frame: $changed (fraction $fraction, need >= $MIN_FRACTION)"
if python3 -c "import sys; sys.exit(0 if float('$fraction') >= float('$MIN_FRACTION') else 1)"; then
    echo "RESULT: cube colour changed (PASS)"
    exit 0
fi
echo "RESULT: cube colour did NOT change enough (FAIL)"
exit 1
