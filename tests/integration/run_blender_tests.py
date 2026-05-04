#!/usr/bin/env python3
"""
Run pytest inside Blender's Python.

Usage:
    blender --background --python /absolute/path/to/run_blender_tests.py

Or via Make:
    make test-blender
"""

import os
import sys
import types
import site

_USER_SITE = site.getusersitepackages()
if _USER_SITE and _USER_SITE not in sys.path:
    sys.path.insert(0, _USER_SITE)


# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_SKP_LINK_DIR = os.path.normpath(os.path.join(_TEST_DIR, "..", ".."))

if _SKP_LINK_DIR not in sys.path:
    sys.path.insert(0, _SKP_LINK_DIR)


# ---------------------------------------------------------------------------
# Stub the Cython sketchup module
# ---------------------------------------------------------------------------

_sketchup_stub = types.ModuleType("blender_plugin.sketchup")
_sketchup_stub.__package__ = "blender_plugin"


class _StubModel:
    """Stub that satisfies `from . import sketchup`."""
    @staticmethod
    def from_file(path):
        return None


_sketchup_stub.Model = _StubModel
sys.modules["blender_plugin.sketchup"] = _sketchup_stub


# ---------------------------------------------------------------------------
# Register addons
# ---------------------------------------------------------------------------

import bpy  # noqa: E402

# Enable the addon so context.preferences.addons has the entry that
# SceneImporter.load() needs for self.prefs.
if "blender_plugin" not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module="blender_plugin")


# ---------------------------------------------------------------------------
# Run pytest
# ---------------------------------------------------------------------------

import pytest  # noqa: E402

test_file = os.path.join(_TEST_DIR, "test_blender_import.py")
sys.exit(pytest.main([test_file, "-v", "-s", "--tb=short"]))
