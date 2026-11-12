#!/usr/bin/env bash
# Decide whether a SketchUp material change reached the screen on VisualCube.
#
# Inputs: two PNG captures of the same framed viewport, before and after the change.
# Pass only if the cube's own region changes colour. Any-pixel difference is not enough:
# unrelated redraw (the sun or light gizmo at the viewport edge) also changes pixels.
#
# Exit 0 = the cube changed, 1 = it did not (a real failure), 2 = usage error.
set -euo pipefail
BEFORE="${1:?before.png}"
AFTER="${2:?after.png}"
# The cube fills the centre of the framed viewport; sample a window inside it.
REGION="${CUBE_REGION:-200x200+500+500}"

# Mean RGB (0-255) of the sampled cube window. Rounding noise changes the last decimal;
# a real material change moves a channel by tens of levels, so require a large delta.
MIN_DELTA="${MIN_DELTA:-40}"

mean_rgb() {
    convert "$1" -crop "$REGION" -resize 1x1! -format '%[fx:255*r] %[fx:255*g] %[fx:255*b]' info: 2>/dev/null
}
b="$(mean_rgb "$BEFORE")"
a="$(mean_rgb "$AFTER")"
echo "before cube mean RGB: $b"
echo "after  cube mean RGB: $a"
delta="$(python3 -c "
b=[float(v) for v in '$b'.split()]; a=[float(v) for v in '$a'.split()]
print(round(max(abs(x-y) for x,y in zip(b,a)),1))")"
echo "max channel delta: $delta (threshold $MIN_DELTA)"
if python3 -c "import sys; sys.exit(0 if float('$delta') >= float('$MIN_DELTA') else 1)"; then
    echo "RESULT: cube colour changed (PASS)"
else
    echo "RESULT: cube colour did NOT change (FAIL)"
    exit 1
fi
exit 0
