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
_IMPORTER_DIR = os.path.normpath(os.path.join(_SKP_LINK_DIR, "..", "Sketchup_Importer"))

for p in (_SKP_LINK_DIR, _IMPORTER_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

# ---------------------------------------------------------------------------
# Stub the Cython sketchup module
# ---------------------------------------------------------------------------

_sketchup_stub = types.ModuleType("sketchup_importer.sketchup")
_sketchup_stub.__package__ = "sketchup_importer"


class _StubModel:
    """Stub that satisfies `from . import sketchup`."""
    @staticmethod
    def from_file(path):
        return None


_sketchup_stub.Model = _StubModel
sys.modules["sketchup_importer.sketchup"] = _sketchup_stub

# ---------------------------------------------------------------------------
# Register addons
# ---------------------------------------------------------------------------

import bpy  # noqa: E402
import sketchup_importer  # noqa: E402

# Enable the addon so context.preferences.addons has the entry that
# SceneImporter.load() needs for self.prefs.
if "sketchup_importer" not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module="sketchup_importer")

# ---------------------------------------------------------------------------
# Run pytest
# ---------------------------------------------------------------------------

import pytest  # noqa: E402

test_file = os.path.join(_TEST_DIR, "test_blender_import.py")
sys.exit(pytest.main([test_file, "-v", "-s", "--tb=short"]))
