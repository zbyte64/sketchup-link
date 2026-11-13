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


def test_texture_cleanup_never_removes_the_system_temp_dir():
    """Regression: the texture cleanup built its directory from the file name. On live
    import the file name is empty, so the directory became the system temp dir, and
    shutil.rmtree deleted all of /tmp (ignore_errors hid it). Every texture cleanup must
    remove only a directory it created with mkdtemp, never gettempdir() or a name-derived
    path."""
    src = _source()
    # The removed pattern: a temp dir joined with a name derived from the file path.
    assert "temp_dir += os.path.sep + skp_fname" not in src
    assert "skp_fname = self.filepath" not in src
    # Every rmtree of a texture temp dir must target a mkdtemp result.
    for match in re.finditer(r"temp_dir = (tempfile\.\w+)\(", src):
        assert match.group(1) == "tempfile.mkdtemp", f"texture temp dir from {match.group(1)}"


def test_existing_material_is_updated_from_snapshot_not_kept():
    """Regression: the material block created a material only when absent, so a SketchUp
    colour change never reached a material Blender had already imported. Every sync after the
    first kept the first colour. An existing material must be updated from the snapshot."""
    src = _source()
    assert "_update_existing_material" in src, "existing materials are not updated from the snapshot"
    assert "self._update_existing_material(bpy.data.materials[name], mat)" in src


def _material_alpha():
    """Load material_alpha from the importer source alone (the module imports bpy, which tests lack)."""
    tree = ast.parse(_source())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "material_alpha")
    ns: dict = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<material_alpha>", "exec"), ns)
    return ns["material_alpha"]


class _Mat:
    def __init__(self, opacity=None):
        if opacity is not None:
            self.opacity = opacity


def test_material_alpha_uses_opacity_for_translucent_glass():
    """SketchUp keeps translucency in opacity (0..1); the colour alpha is 255. Glass at 0.4 must import at 0.4."""
    assert _material_alpha()(_Mat(0.4), 255) == 0.4


def test_material_alpha_opaque_when_opacity_is_one():
    assert _material_alpha()(_Mat(1.0), 255) == 1.0


def test_material_alpha_falls_back_to_colour_alpha_without_opacity():
    assert _material_alpha()(_Mat(), 128) == round(128 / 255.0, 2)


def test_material_alpha_clamps_out_of_range_opacity():
    assert _material_alpha()(_Mat(1.7), 255) == 1.0
    assert _material_alpha()(_Mat(-0.2), 255) == 0.0


def test_named_scene_import_takes_hidden_layers_from_the_model():
    """A named-scene import must exclude hidden layers the same way the live import does.

    The scene branch used to read s.layers, which the adapter's JsonScene does not expose (AttributeError on any
    named-scene import). Hidden layers come from the model's own layer flags, shared with the live path, so both
    paths agree. This asserts the scene branch reads the model's hidden layers and not a scene attribute.
    """
    src = _source()
    assert "s.layers" not in src, "the scene branch reads s.layers, which JsonScene does not expose"
    assert "hidden_layers_for_live" in src
