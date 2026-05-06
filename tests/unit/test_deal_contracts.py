"""Property-based tests generated from deal contracts on adapter classes."""
from __future__ import annotations

import deal

from blender_plugin.live_adapter import JsonLayer, _JsonColor, _flat_to_4x4

# ──────────────────────────────────────────────
# _flat_to_4x4 — contract already on the source
# (pre: None or 16-element list; post: 4×4 list)
# ──────────────────────────────────────────────
test_flat_to_4x4 = deal.cases(_flat_to_4x4)


# ──────────────────────────────────────────────
# _JsonColor — __iter__ yields exactly 4 values
# (r, g, b, a) regardless of input content
# ──────────────────────────────────────────────
@deal.ensure(lambda d, result: isinstance(result, tuple) and len(result) == 4)
def _json_color_items(d: dict) -> tuple:
    """Return the 4 values from _JsonColor as a tuple."""
    return tuple(_JsonColor(d))


test_json_color_items = deal.cases(_json_color_items)


# ──────────────────────────────────────────────
# JsonLayer — eq/hash consistency
# a == b  ⇒  hash(a) == hash(b)
# Use dict params so hypothesis generates inputs;
# JsonLayer wrapping happens inside the function.
# ──────────────────────────────────────────────
@deal.ensure(
    lambda a, b, result: not (JsonLayer(a) == JsonLayer(b))
    or hash(JsonLayer(a)) == hash(JsonLayer(b)),
    message="a == b must imply hash(a) == hash(b)",
)
def _json_layer_eq_hash_consistent(a: dict, b: dict) -> bool:
    """a == b → hash(a) == hash(b)."""
    return JsonLayer(a) == JsonLayer(b)


test_json_layer_eq_hash = deal.cases(_json_layer_eq_hash_consistent)
