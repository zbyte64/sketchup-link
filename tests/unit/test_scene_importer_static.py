"""Static regression checks for blender_plugin/scene_importer.py.

These run without Blender (bpy is not importable at test time), so they
inspect the source text for removed Blender 2.7x APIs and duplicated
control-flow in SceneImporter.load().
"""

import ast
import pathlib
import re

SCENE_IMPORTER = pathlib.Path(__file__).resolve().parents[2] / "blender_plugin" / "scene_importer.py"


def _source() -> str:
    return SCENE_IMPORTER.read_text(encoding="utf-8")


def _load_body_calls() -> list[str]:
    tree = ast.parse(_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SceneImporter":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "load":
                    calls = []
                    for sub in ast.walk(item):
                        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                            if isinstance(sub.func.value, ast.Name) and sub.func.value.id == "self":
                                calls.append(sub.func.attr)
                    return calls
    raise AssertionError("SceneImporter.load not found")


def test_no_removed_tessfaces_api_on_blender_mesh():
    # Only the duck-typed SketchUp face read (`f.tessfaces`) may remain.
    for lineno, line in enumerate(_source().splitlines(), 1):
        if "tessfaces" in line:
            assert "f.tessfaces" in line, f"line {lineno} uses Blender tessfaces API: {line!r}"


def test_no_legacy_layers_assignment():
    assert not re.search(r"\.layers\s*=", _source()), "legacy object .layers assignment remains"


def test_no_legacy_matrix_multiply_operator():
    src = _source()
    assert "Matrix.Translation(" not in src or " @ " in src
    assert not re.search(r"Matrix\.Translation\([^)]*\)\s*\*", src)
    assert not re.search(r"\bmat\s*\*\s*Vector", src)


def test_write_duplicateable_groups_called_once_in_load():
    calls = _load_body_calls()
    assert calls.count("write_duplicateable_groups") == 1


def test_dedub_only_early_return_not_duplicated():
    tree = ast.parse(_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SceneImporter":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "load":
                    count = 0
                    for sub in ast.walk(item):
                        if isinstance(sub, ast.If):
                            test_src = ast.unparse(sub.test)
                            if "dedub_only" in test_src:
                                count += 1
                    assert count == 1
                    return
    raise AssertionError("SceneImporter.load not found")
