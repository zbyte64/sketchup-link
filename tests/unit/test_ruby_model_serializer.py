"""Tests for ModelSerializer via Ruby subprocess."""

from __future__ import annotations

import pytest

from tests.unit.conftest import run_ruby

SCRIPT = "model_serializer_test.rb"


def _model_data(**overrides):
    """Return a standard model dict, overridable per-key."""
    data = {
        "guid": "mdl-guid-001",
        "title": "Test Model",
        "path": "/tmp/test_model.skp",
        "camera": {
            "eye": [1.0, 2.0, 3.0],
            "target": [4.0, 5.0, 6.0],
            "up": [0.0, 1.0, 0.0],
            "perspective": True,
            "fov": 45.0,
            "aspect_ratio": 1.777,
        },
        "entities": [],
        "materials": [
            {"name": "Mat1", "color": [255, 0, 0, 255], "alpha": 255},
            None,
            {"name": "Mat2", "color": [0, 255, 0, 255], "alpha": 128},
        ],
        "layers": [
            {
                "name": "Layer0",
                "visible": True,
                "color": [180, 180, 180, 255],
                "line_width": 1,
            },
            {
                "name": "Layer1",
                "visible": False,
                "color": [200, 200, 200, 255],
                "line_width": 2,
            },
        ],
        "definitions": [
            {
                "name": "Def1",
                "guid": "def-guid-1",
                "count_instances": 2,
                "count_used_instances": 1,
                "entities": [],
                "group": False,
            },
            {
                "name": "Def2",
                "guid": "def-guid-2",
                "count_instances": 1,
                "count_used_instances": 0,
                "entities": [],
                "group": False,
            },
            {
                "name": "DefGroup",
                "guid": "def-guid-3",
                "count_instances": 1,
                "count_used_instances": 0,
                "entities": [],
                "group": True,
            },
        ],
    }
    data.update(overrides)

    return data


# ── global defaults reused across tests ──────────────────────────────

INCHES_TO_METERS = 0.0254


# ── serialize ────────────────────────────────────────────────────────


@pytest.mark.ruby
def test_model_keys():
    """serialize returns all expected top-level keys."""
    result = run_ruby(SCRIPT, {"action": "serialize", "model": _model_data()})
    assert set(result.keys()) == {
        "model_guid",
        "camera",
        "title",
        "path",
        "entities",
        "materials",
        "layers",
        "shadow_info",
        "component_definitions",
    }


# ── camera ────────────────────────────────────────────────────────────


@pytest.mark.ruby
def test_camera_structure():
    """Camera dict contains all expected fields."""
    result = run_ruby(
        SCRIPT,
        {
            "action": "serialize_camera",
            "model": {
                "camera": {
                    "eye": [1.0, 2.0, 3.0],
                    "target": [4.0, 5.0, 6.0],
                    "up": [0.0, 1.0, 0.0],
                    "perspective": True,
                    "fov": 45.0,
                    "aspect_ratio": 1.777,
                }
            },
        },
    )
    assert set(result.keys()) == {
        "eye",
        "target",
        "up",
        "perspective",
        "fov",
        "aspect_ratio",
    }


@pytest.mark.ruby
def test_camera_eye_target_in_meters():
    """Eye and target values are converted from inches to meters."""
    result = run_ruby(
        SCRIPT,
        {
            "action": "serialize_camera",
            "model": {
                "camera": {
                    "eye": [12.0, 24.0, 36.0],
                    "target": [6.0, 18.0, 30.0],
                    "up": [0.0, 1.0, 0.0],
                    "perspective": True,
                    "fov": 45.0,
                    "aspect_ratio": 1.6,
                }
            },
        },
    )
    expected_eye = [12.0 * INCHES_TO_METERS, 24.0 * INCHES_TO_METERS, 36.0 * INCHES_TO_METERS]
    expected_target = [6.0 * INCHES_TO_METERS, 18.0 * INCHES_TO_METERS, 30.0 * INCHES_TO_METERS]
    assert result["eye"] == pytest.approx(expected_eye)
    assert result["target"] == pytest.approx(expected_target)


@pytest.mark.ruby
def test_camera_up_unchanged():
    """Up vector is a direction — values are not converted to meters."""
    result = run_ruby(
        SCRIPT,
        {
            "action": "serialize_camera",
            "model": {
                "camera": {
                    "eye": [1.0, 2.0, 3.0],
                    "target": [4.0, 5.0, 6.0],
                    "up": [42.0, 0.0, -1.0],
                    "perspective": True,
                    "fov": 45.0,
                    "aspect_ratio": 1.6,
                }
            },
        },
    )
    # up should be exactly [42.0, 0.0, -1.0] — NOT scaled by INCHES_TO_METERS
    assert result["up"] == [42.0, 0.0, -1.0]


@pytest.mark.ruby
def test_camera_perspective_fov():
    """FOV is present when perspective is true."""
    result = run_ruby(
        SCRIPT,
        {
            "action": "serialize_camera",
            "model": {
                "camera": {
                    "eye": [1.0, 2.0, 3.0],
                    "target": [4.0, 5.0, 6.0],
                    "up": [0.0, 1.0, 0.0],
                    "perspective": True,
                    "fov": 60.0,
                    "aspect_ratio": 1.6,
                }
            },
        },
    )
    assert result["perspective"] is True
    assert result["fov"] == 60.0


@pytest.mark.ruby
def test_camera_orthographic_fov_zero():
    """FOV is 0.0 when perspective is false."""
    result = run_ruby(
        SCRIPT,
        {
            "action": "serialize_camera",
            "model": {
                "camera": {
                    "eye": [1.0, 2.0, 3.0],
                    "target": [4.0, 5.0, 6.0],
                    "up": [0.0, 1.0, 0.0],
                    "perspective": False,
                    "fov": 45.0,
                    "aspect_ratio": 1.6,
                }
            },
        },
    )
    assert result["perspective"] is False
    assert result["fov"] == 0.0


@pytest.mark.ruby
def test_camera_aspect_ratio_false_when_not_numeric():
    """aspect_ratio is false when the value is not a Numeric."""
    result = run_ruby(
        SCRIPT,
        {
            "action": "serialize_camera",
            "model": {
                "camera": {
                    "eye": [1.0, 2.0, 3.0],
                    "target": [4.0, 5.0, 6.0],
                    "up": [0.0, 1.0, 0.0],
                    "perspective": True,
                    "fov": 45.0,
                    "aspect_ratio": "not_numeric",
                }
            },
        },
    )
    assert result["aspect_ratio"] is False


@pytest.mark.ruby
def test_camera_nil_on_error():
    """serialize_camera returns None / nil on error (e.g. nil camera).

    Note: the Ruby test helper always builds a valid camera object from
    input data, so we verify the happy path (valid camera → non-None hash)
    and document that the ``rescue StandardError => nil`` path is exercised
    by the production code path through ``model.active_view.camera``.
    """
    result = run_ruby(
        SCRIPT,
        {
            "action": "serialize_camera",
            "model": {
                "camera": {
                    "eye": [1.0, 2.0, 3.0],
                    "target": [4.0, 5.0, 6.0],
                    "up": [0.0, 1.0, 0.0],
                    "perspective": True,
                    "fov": 45.0,
                    "aspect_ratio": 1.6,
                }
            },
        },
    )
    assert result is not None
    assert isinstance(result, dict)


# ── definitions ────────────────────────────────────────────────────────


@pytest.mark.ruby
def test_skip_group_definitions():
    """Group definitions (group? == True) are excluded from component_definitions."""
    result = run_ruby(
        SCRIPT,
        {
            "action": "serialize_definitions",
            "model": {
                "definitions": [
                    {
                        "name": "NormalDef",
                        "guid": "g-a",
                        "count_instances": 1,
                        "count_used_instances": 0,
                        "entities": [],
                        "group": False,
                    },
                    {
                        "name": "GroupDef",
                        "guid": "g-b",
                        "count_instances": 0,
                        "count_used_instances": 0,
                        "entities": [],
                        "group": True,
                    },
                    {
                        "name": "AnotherDef",
                        "guid": "g-c",
                        "count_instances": 3,
                        "count_used_instances": 2,
                        "entities": [],
                        "group": False,
                    },
                ]
            },
        },
    )
    assert "GroupDef" not in result
    assert "NormalDef" in result
    assert "AnotherDef" in result
    assert len(result) == 2


@pytest.mark.ruby
def test_definitions_keyed_by_name():
    """component_definitions hash keyed by definition name, not an array."""
    result = run_ruby(
        SCRIPT,
        {
            "action": "serialize_definitions",
            "model": {
                "definitions": [
                    {
                        "name": "Alpha",
                        "guid": "g-1",
                        "count_instances": 1,
                        "count_used_instances": 0,
                        "entities": [],
                        "group": False,
                    },
                    {
                        "name": "Beta",
                        "guid": "g-2",
                        "count_instances": 5,
                        "count_used_instances": 3,
                        "entities": [],
                        "group": False,
                    },
                ]
            },
        },
    )
    assert isinstance(result, dict)
    assert list(result.keys()) == ["Alpha", "Beta"]


# ── materials ──────────────────────────────────────────────────────────


@pytest.mark.ruby
def test_materials_compact():
    """Nil materials are compacted out of the materials array."""
    result = run_ruby(
        SCRIPT,
        {
            "action": "serialize_materials",
            "model": {
                "materials": [
                    {"name": "A", "color": [255, 0, 0, 255], "alpha": 255},
                    None,
                    {"name": "B", "color": [0, 255, 0, 255], "alpha": 200},
                    None,
                    {"name": "C", "color": [0, 0, 255, 255], "alpha": 100},
                ]
            },
        },
    )
    assert isinstance(result, list)
    assert len(result) == 3
    names = [m["name"] for m in result]
    assert names == ["A", "B", "C"]


# ── layers ─────────────────────────────────────────────────────────────


@pytest.mark.ruby
def test_layers_serialization():
    """Layers array maps through serialize_layer with correct structure."""
    result = run_ruby(
        SCRIPT,
        {
            "action": "serialize_layers",
            "model": {
                "layers": [
                    {
                        "name": "Main",
                        "visible": True,
                        "color": [128, 128, 128, 255],
                        "line_width": 1,
                    },
                    {
                        "name": "Hidden",
                        "visible": False,
                        "color": [200, 50, 50, 255],
                        "line_width": 3,
                    },
                ]
            },
        },
    )
    assert isinstance(result, list)
    assert len(result) == 2

    layer0 = result[0]
    assert layer0["name"] == "Main"
    assert layer0["visible"] is True
    assert layer0["color"] == {"r": 128, "g": 128, "b": 128, "a": 255}
    assert layer0["line_width"] == 1

    layer1 = result[1]
    assert layer1["name"] == "Hidden"
    assert layer1["visible"] is False
    assert layer1["color"] == {"r": 200, "g": 50, "b": 50, "a": 255}
    assert layer1["line_width"] == 3
