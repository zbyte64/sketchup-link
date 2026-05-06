"""
Invariant checker functions for fuzzing.

Each invariant is a function:
    check(model_json, event_log) -> list[dict]

Returns a list of violation dicts (empty list = no violations).
Each violation dict has:
    check:   str — invariant name
    passed:  bool — False for violations
    message: str — human-readable description
    details: dict — optional machine-readable context
"""

import json
import math


# ------------------------------------------------------------------
# Violation helper
# ------------------------------------------------------------------


def _violation(check, message, details=None):
    return {
        "check": check,
        "passed": False,
        "message": message,
        "details": details or {},
    }


# ------------------------------------------------------------------
# Invariant checkers
# ------------------------------------------------------------------


def check_json_valid(model_json, event_log=None):
    """Model JSON is parseable and has required top-level keys."""
    violations = []
    required_keys = {"entities", "materials", "layers", "component_definitions"}
    missing = required_keys - set(model_json.keys())
    if missing:
        violations.append(_violation(
            "json_valid",
            f"Missing required top-level keys: {missing}",
            {"missing_keys": list(missing), "present_keys": list(model_json.keys())},
        ))
    # Check entities is a list
    entities = model_json.get("entities")
    if not isinstance(entities, list):
        violations.append(_violation(
            "json_valid",
            f"'entities' should be a list, got {type(entities).__name__}",
            {"type": str(type(entities).__name__)},
        ))
    # Check materials is a list
    materials = model_json.get("materials")
    if not isinstance(materials, list):
        violations.append(_violation(
            "json_valid",
            f"'materials' should be a list, got {type(materials).__name__}",
            {"type": str(type(materials).__name__)},
        ))
    # Check layers is a list
    layers = model_json.get("layers")
    if not isinstance(layers, list):
        violations.append(_violation(
            "json_valid",
            f"'layers' should be a list, got {type(layers).__name__}",
            {"type": str(type(layers).__name__)},
        ))
    return violations


def check_no_dangling_material_refs(model_json, event_log=None):
    """Every material name referenced by entities exists in materials list."""
    violations = []
    materials = {m.get("name") for m in model_json.get("materials", []) if m.get("name")}
    entities = model_json.get("entities", [])

    for entity in entities:
        for key in ("material", "back_material"):
            ref = entity.get(key)
            if ref is not None and ref not in materials:
                violations.append(_violation(
                    "no_dangling_material_refs",
                    f"Entity pid={entity.get('persistent_id')} references "
                    f"material '{ref}' which does not exist in materials list",
                    {
                        "persistent_id": entity.get("persistent_id"),
                        "entity_type": entity.get("type"),
                        "ref_key": key,
                        "ref_value": ref,
                        "available_materials": list(materials),
                    },
                ))

    return violations


def check_no_dangling_layer_refs(model_json, event_log=None):
    """Every layer name referenced by entities exists in layers list."""
    violations = []
    layers = {l.get("name") for l in model_json.get("layers", []) if l.get("name")}
    entities = model_json.get("entities", [])

    for entity in entities:
        ref = entity.get("layer")
        if ref is not None and ref not in layers:
            violations.append(_violation(
                "no_dangling_layer_refs",
                f"Entity pid={entity.get('persistent_id')} references "
                f"layer '{ref}' which does not exist in layers list",
                {
                    "persistent_id": entity.get("persistent_id"),
                    "entity_type": entity.get("type"),
                    "ref_value": ref,
                    "available_layers": list(layers),
                },
            ))

    return violations


def check_valid_transforms(model_json, event_log=None):
    """All transform matrices are valid: no NaN/Inf, det ≈ 1 for rotation parts."""
    violations = []
    entities = model_json.get("entities", [])

    for entity in entities:
        transform = entity.get("transformation")
        if transform is None:
            continue
        if not isinstance(transform, list) or len(transform) != 16:
            violations.append(_violation(
                "valid_transforms",
                f"Entity pid={entity.get('persistent_id')} has invalid transform shape",
                {
                    "persistent_id": entity.get("persistent_id"),
                    "transform": transform,
                },
            ))
            continue

        # Check for NaN/Inf
        for i, val in enumerate(transform):
            if not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
                violations.append(_violation(
                    "valid_transforms",
                    f"Entity pid={entity.get('persistent_id')} has "
                    f"invalid transform value at index {i}: {val}",
                    {
                        "persistent_id": entity.get("persistent_id"),
                        "index": i,
                        "value": val,
                    },
                ))

        # Compute determinant of the 3x3 rotation submatrix (indices 0,1,2,4,5,6,8,9,10)
        try:
            a = transform[0:3]
            b = transform[4:7]
            c = transform[8:11]
            det = (a[0] * (b[1] * c[2] - b[2] * c[1])
                   - a[1] * (b[0] * c[2] - b[2] * c[0])
                   + a[2] * (b[0] * c[1] - b[1] * c[0]))
            if abs(abs(det) - 1.0) > 0.01:
                violations.append(_violation(
                    "valid_transforms",
                    f"Entity pid={entity.get('persistent_id')} has "
                    f"transform det={det:.6f} (expected ≈1.0)",
                    {
                        "persistent_id": entity.get("persistent_id"),
                        "determinant": round(det, 6),
                        "transform": transform,
                    },
                ))
        except (IndexError, TypeError, ValueError):
            violations.append(_violation(
                "valid_transforms",
                f"Entity pid={entity.get('persistent_id')} has "
                f"uncomputable transform determinant",
                {"persistent_id": entity.get("persistent_id"), "transform": transform},
            ))

    return violations


def check_non_degenerate_faces(model_json, event_log=None):
    """Every face has ≥ 3 vertices, non-zero area."""
    violations = []
    entities = model_json.get("entities", [])

    for entity in entities:
        if entity.get("type") != "Face":
            continue
        verts = entity.get("vertices", [])
        if len(verts) < 3:
            violations.append(_violation(
                "non_degenerate_faces",
                f"Face pid={entity.get('persistent_id')} has "
                f"only {len(verts)} vertices (minimum 3)",
                {
                    "persistent_id": entity.get("persistent_id"),
                    "vertex_count": len(verts),
                },
            ))

        # Check for degenerate (zero-area) faces
        area = entity.get("area")
        if area is not None and isinstance(area, (int, float)):
            if area <= 0:
                violations.append(_violation(
                    "non_degenerate_faces",
                    f"Face pid={entity.get('persistent_id')} has "
                    f"zero or negative area: {area}",
                    {
                        "persistent_id": entity.get("persistent_id"),
                        "area": area,
                    },
                ))

    return violations


def check_entity_ids_unique(model_json, event_log=None):
    """No duplicate persistent_ids across all entities."""
    violations = []
    entities = model_json.get("entities", [])
    seen_pids = {}

    for entity in entities:
        pid = entity.get("persistent_id")
        if pid is None:
            continue
        if pid in seen_pids:
            violations.append(_violation(
                "entity_ids_unique",
                f"Duplicate persistent_id {pid} found",
                {
                    "persistent_id": pid,
                    "count": sum(1 for e in entities if e.get("persistent_id") == pid),
                },
            ))
        seen_pids[pid] = True

    return violations


def check_component_defs_intact(model_json, event_log=None):
    """All component definition names referenced by instances exist."""
    violations = []
    defs = {name for name in model_json.get("component_definitions", {})}
    entities = model_json.get("entities", [])

    for entity in entities:
        if entity.get("type") != "ComponentInstance":
            continue
        ref = entity.get("definition_name")
        if ref is None:
            violations.append(_violation(
                "component_defs_intact",
                f"ComponentInstance pid={entity.get('persistent_id')} "
                f"has no definition_name",
                {"persistent_id": entity.get("persistent_id")},
            ))
        elif ref not in defs:
            violations.append(_violation(
                "component_defs_intact",
                f"ComponentInstance pid={entity.get('persistent_id')} "
                f"references definition '{ref}' which does not exist",
                {
                    "persistent_id": entity.get("persistent_id"),
                    "definition_name": ref,
                    "available_definitions": list(defs),
                },
            ))

    return violations


def check_model_roundtrips(model_json, event_log=None):
    """JsonModel(model_json) can be constructed and basic properties accessed."""
    violations = []
    try:
        from blender_plugin.live_adapter import JsonModel
        model = JsonModel(model_json)
        # Access basic properties to ensure no crashes
        _ = list(model.entities)
        _ = list(model.materials)
        _ = list(model.layers)
        _ = list(model.component_definitions)
        _ = list(model.entities.faces)
        _ = list(model.entities.groups)
        _ = list(model.entities.instances)
        # Access face tessellation data
        for face in model.entities.faces:
            _ = face.tessfaces
            _ = face.material
            _ = face.back_material
        # Access group/instance transforms
        for group in model.entities.groups:
            _ = group.transform
        for inst in model.entities.instances:
            _ = inst.transform
            _ = inst.definition
    except Exception as exc:
        violations.append(_violation(
            "model_roundtrips",
            f"JsonModel construction or property access failed: {exc}",
            {"error": str(exc), "error_type": type(exc).__name__},
        ))

    return violations


def check_screenshot_stable(model_json, event_log=None):
    """Placeholder: pixel-diff check requires screenshot paths.

    This invariant is checked externally by the test runner.
    """
    return []


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------

ALL_INVARIANTS = [
    ("json_valid", check_json_valid),
    ("no_dangling_material_refs", check_no_dangling_material_refs),
    ("no_dangling_layer_refs", check_no_dangling_layer_refs),
    ("valid_transforms", check_valid_transforms),
    ("non_degenerate_faces", check_non_degenerate_faces),
    ("entity_ids_unique", check_entity_ids_unique),
    ("component_defs_intact", check_component_defs_intact),
    ("model_roundtrips", check_model_roundtrips),
]


def check_all(model_json, event_log=None):
    """Run all invariant checkers and return a consolidated list of violations.

    Args:
        model_json: dict — the model JSON snapshot.
        event_log: optional EventLogger instance — violations are logged.

    Returns:
        list of violation dicts (empty = all invariants passed).
    """
    all_violations = []
    for name, checker in ALL_INVARIANTS:
        try:
            violations = checker(model_json, event_log)
            all_violations.extend(violations)
            if event_log:
                for v in violations:
                    event_log.assertion(name, passed=False, details=v)
        except Exception as exc:
            violation = _violation(
                name,
                f"Checker raised exception: {exc}",
                {"error": str(exc), "error_type": type(exc).__name__},
            )
            all_violations.append(violation)
            if event_log:
                event_log.assertion(name, passed=False, details=violation)
    return all_violations
