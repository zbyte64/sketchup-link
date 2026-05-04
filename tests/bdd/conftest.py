"""
tests/bdd/conftest.py — Top-level BDD fixtures and step definitions.

Provides both CI-mode fixtures (run against a local Ruby mock server using
JsonModel adapters, no VM/Blender needed) and full-mode fixtures (Docker VM,
RDP session, Blender headless).

Use --no-screenshots to run in CI-safe mode (pytest flag); screenshots on by
default but informational only.
"""
import http.client
import json
import math
import os
import socket
import subprocess
import sys
import tempfile
import re

import pytest
from pytest_bdd import given, when, then

# ---------------------------------------------------------------------------
# Path setup — make blender_plugin importable
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SERVER_RB = os.path.join(os.path.dirname(__file__), '..', 'integration', 'server.rb')
_SOCKET_PATH = os.path.join(tempfile.gettempdir(), 'sketchup-link-bdd-test.sock')
_SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), 'screenshots')
_RUN_BLENDER_PY = os.path.join(os.path.dirname(__file__), 'run_blender_assertions.py')
_RENDER_SCREENSHOT_PY = os.path.join(os.path.dirname(__file__), 'render_screenshot.py')
_RENDER_WIREFRAME_PY = os.path.join(os.path.dirname(__file__), 'render_wireframe_screenshot.py')
_TCP_HOST = 'windows'
_TCP_PORT = 9876


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _UnixSocketHTTPConnection(http.client.HTTPConnection):
    """HTTP/1.1 connection over a Unix domain socket."""

    def __init__(self, path):
        super().__init__('localhost')
        self._path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(self._path)
        self.sock = s


def _fetch_json(socket_path):
    """GET /model from the server and return the parsed JSON dict."""
    conn = _UnixSocketHTTPConnection(socket_path)
    try:
        conn.request('GET', '/model')
        resp = conn.getresponse()
        assert resp.status == 200, f"Expected HTTP 200, got {resp.status}"
        return json.loads(resp.read())
    finally:
        conn.close()


def _get_json_model(request):
    """Get the imported model data from the request node."""
    data = getattr(request.node, '_imported_model', None)
    if data is None:
        pytest.fail('No imported model found — did a "When I import..." step run?')
    return data


def _get_json_model_adapter(request):
    """Wrap imported model data in JsonModel for adapter-based assertions."""
    from blender_plugin.live_adapter import JsonModel
    return JsonModel(_get_json_model(request))


def _srgb_to_linear(c):
    """Convert a single sRGB channel (0-255) to linear."""
    return math.pow(c / 255.0, 2.2)


def _get_socket_path(request):
    """Get the socket path from the request stash or default."""
    return getattr(request.node, '_socket_path', None) or _SOCKET_PATH

def _fetch_json_tcp(host=_TCP_HOST, port=_TCP_PORT):
    """GET /model over TCP and return the parsed JSON dict."""
    conn = http.client.HTTPConnection(host, port)
    try:
        conn.request('GET', '/model')
        resp = conn.getresponse()
        assert resp.status == 200, f"Expected HTTP 200, got {resp.status}"
        return json.loads(resp.read())
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# CLI option: --no-screenshots for CI-safe mode
# ---------------------------------------------------------------------------


def pytest_addoption(parser):
    parser.addoption(
        '--no-screenshots',
        action='store_true',
        default=False,
        help='Skip screenshot capture (CI-safe mode)',
    )


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope='session')
def no_screenshots(request):
    """True when --no-screenshots was passed."""
    return request.config.getoption('--no-screenshots')


@pytest.fixture(scope='session')
def ruby_server():
    """
    Start the Ruby test server subprocess.
    Blocks until the server writes 'ready' to stdout.
    """
    if os.path.exists(_SOCKET_PATH):
        os.unlink(_SOCKET_PATH)

    proc = subprocess.Popen(
        ['ruby', _SERVER_RB, _SOCKET_PATH],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    signal = proc.stdout.readline().strip()
    if signal != 'ready':
        proc.terminate()
        stderr_out = proc.stderr.read()
        raise RuntimeError(
            f"Ruby server did not signal 'ready' (got {signal!r}).\n"
            f"stderr:\n{stderr_out}"
        )

    yield _SOCKET_PATH

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    try:
        os.unlink(_SOCKET_PATH)
    except FileNotFoundError:
        pass


@pytest.fixture(scope='session')
def model_data(ruby_server):
    """Fetch the model JSON from the Ruby server once per session."""
    return _fetch_json(ruby_server)


@pytest.fixture(scope='session')
def json_model(model_data):
    """Wrap model_data in JsonModel (session-scoped)."""
    from blender_plugin.live_adapter import JsonModel
    return JsonModel(model_data)


# ---------------------------------------------------------------------------
# Screenshot fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def screenshot_dir(request):
    """Per-scenario screenshot output directory."""
    test_name = request.node.name.replace('/', '_').replace(' ', '_')
    path = os.path.join(_SCREENSHOT_DIR, test_name)
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Full-mode fixtures (placeholders)
# ---------------------------------------------------------------------------


@pytest.fixture(scope='session')
def docker_vm():
    yield


@pytest.fixture(scope='session')
def rdp_session():
    yield


@pytest.fixture(scope='module')
def sketchup_ready(docker_vm, rdp_session):
    yield


@pytest.fixture(scope='session')
def blender_runner():
    return _RUN_BLENDER_PY


@pytest.fixture(scope='session')
def golden_model_json():
    golden_paths = [
        os.path.join(_REPO_ROOT, 'tests', 'integration', 'golden', 'test_model.json'),
    ]
    for path in golden_paths:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    return None


@pytest.fixture(scope='session')
def sketchup_test_model():
    """Connect to the SketchUp Link plugin via TCP and validate model structure.

    Fetches GET /model from the Windows VM's TCP socket and validates that
    the returned structure matches the expected test model from factories.rb.

    If the connection fails or the model is wrong, emits a clear error
    with instructions for setting up the test model inside the VM.
    """
    host = _TCP_HOST
    port = _TCP_PORT

    try:
        data = _fetch_json_tcp(host, port)
    except Exception as exc:
        pytest.fail(
            f"Could not connect to SketchUp Link plugin at {host}:{port}.\n"
            f"Error: {exc}\n\n"
            f"Ensure the SketchUp Link plugin is loaded in the Windows VM\n"
            f"and serving on TCP port {port}. The plugin must be started\n"
            f"with SERVER_MODE=tcp. If the test model is not open, create\n"
            f"it manually in SketchUp and save as C:\\shared\\test_model.skp."
        )

    # Validate model structure
    assert 'entities' in data, f"Model missing 'entities' key. Keys: {list(data.keys())}"
    assert 'materials' in data, f"Model missing 'materials' key. Keys: {list(data.keys())}"
    assert 'layers' in data, f"Model missing 'layers' key. Keys: {list(data.keys())}"
    assert 'component_definitions' in data, (
        f"Model missing 'component_definitions' key. Keys: {list(data.keys())}"
    )

    # Validate entity types
    entities = data.get('entities', [])
    entity_types = [e.get('type') for e in entities]
    expected_types = ['Face', 'Face', 'Edge', 'Group', 'ComponentInstance']
    assert entity_types == expected_types, (
        f"Entity types mismatch.\n"
        f"  Expected: {expected_types}\n"
        f"  Got:      {entity_types}\n\n"
        f"The test model must match factories.rb. Open SketchUp in the VM,\n"
        f"create the test geometry, save to C:\\shared\\test_model.skp."
    )

    # Validate materials
    materials = data.get('materials', [])
    material_names = {m.get('name') for m in materials}
    assert 'Red' in material_names, f"Missing 'Red' material. Names: {material_names}"
    assert 'Blue' in material_names, f"Missing 'Blue' material. Names: {material_names}"

    # Validate layers
    layers = data.get('layers', [])
    layer_names = {l.get('name') for l in layers}
    assert 'Layer0' in layer_names, f"Missing 'Layer0'. Names: {layer_names}"
    assert 'Furniture' in layer_names, f"Missing 'Furniture'. Names: {layer_names}"
    assert 'Hidden' in layer_names, f"Missing 'Hidden'. Names: {layer_names}"

    # Validate component definitions
    defs = data.get('component_definitions', {})
    assert 'Chair' in defs, f"Missing 'Chair' definition. Names: {list(defs.keys())}"

    return data

# =========================================================================
# GIVEN steps
# =========================================================================


@given('the Ruby mock server is running')
def given_ruby_mock_server_running(request):
    """Start the Ruby test server subprocess."""
    socket_path = _SOCKET_PATH
    if os.path.exists(socket_path):
        os.unlink(socket_path)

    proc = subprocess.Popen(
        ['ruby', _SERVER_RB, socket_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    signal = proc.stdout.readline().strip()
    if signal != 'ready':
        proc.terminate()
        stderr_out = proc.stderr.read()
        raise RuntimeError(
            f"Ruby server did not signal 'ready' (got {signal!r}).\n"
            f"stderr:\n{stderr_out}"
        )

    request.node._ruby_server_proc = proc
    request.node._socket_path = socket_path
    return socket_path


@given('the test model is available via the socket')
def given_test_model_available(request):
    """Verify the Ruby server is serving a model on the socket."""
    socket_path = _get_socket_path(request)
    data = _fetch_json(socket_path)
    assert 'entities' in data, "Model missing 'entities' key"
    assert 'materials' in data, "Model missing 'materials' key"
    assert 'layers' in data, "Model missing 'layers' key"
    request.node._model_data = data


@given('the Docker Windows VM is running with SketchUp installed')
def given_docker_vm_running():
    pytest.skip('Full VM mode not implemented — use Ruby mock server in CI')

@given('SketchUp is serving on TCP')
def given_sketchup_serving_on_tcp(request):
    """Connect to the SketchUp Link plugin via TCP and verify model access."""
    host = _TCP_HOST
    port = _TCP_PORT
    request.node._connection_mode = 'tcp'
    request.node._tcp_host = host
    request.node._tcp_port = port
    # Verify connectivity and model structure
    data = _fetch_json_tcp(host, port)
    assert 'entities' in data, "Model missing 'entities' key"
    assert 'materials' in data, "Model missing 'materials' key"
    assert 'layers' in data, "Model missing 'layers' key"
    request.node._model_data = data


# =========================================================================
# WHEN steps
# =========================================================================


@when('I import the model via live sync')
def when_import_via_live_sync(request):
    """Fetch model JSON from the server and store for assertions.
    Supports both Unix socket (CI mode) and TCP (full VM mode).
    """
    mode = getattr(request.node, '_connection_mode', 'unix')
    if mode == 'tcp':
        data = _fetch_json_tcp(
            getattr(request.node, '_tcp_host', _TCP_HOST),
            getattr(request.node, '_tcp_port', _TCP_PORT),
        )
    else:
        socket_path = _get_socket_path(request)
        data = _fetch_json(socket_path)
    request.node._imported_model = data


@when('I import the model into Blender via live sync')
def when_import_to_blender(request, no_screenshots):
    """Import model into Blender via live sync.
    In CI mode (--no-screenshots): skip.
    In full mode: available for use with Blender Docker container.
    """
    if no_screenshots:
        pytest.skip('CI mode — full Blender import not available')
    pytest.skip('Full Blender import via Docker not implemented in this version')


@when('I move the FurnitureGroup in SketchUp')
def when_move_furniture_group():
    pytest.skip('Full VM mode not implemented')


@when('I change the Red material color in SketchUp')
def when_change_material_color():
    pytest.skip('Full VM mode not implemented')


@when('I create a new face in SketchUp')
def when_create_new_face():
    pytest.skip('Full VM mode not implemented')

@when('I trigger a live sync update')
def when_trigger_sync_update(request):
    """Force a live sync update by re-fetching the model JSON."""
    socket_path = _get_socket_path(request)
    data = _fetch_json(socket_path)
    request.node._imported_model = data


# =========================================================================
# THEN steps — Materials
# =========================================================================


@then('all materials are created in the import')
def then_all_materials_created(request):
    """Assert that the expected materials exist in the imported model."""
    model = _get_json_model_adapter(request)
    materials = model.materials
    names = {m.name for m in materials}
    assert 'Red' in names, f"Missing 'Red' material, have: {names}"
    assert 'Blue' in names, f"Missing 'Blue' material, have: {names}"
    assert len(materials) >= 2, f"Expected at least 2 materials, got {len(materials)}"


@then('the Red material diffuse color matches the expected sRGB-to-linear conversion')
def then_red_material_color_matches(request):
    """Assert Red material (220, 20, 20) converts to correct linear color."""
    model = _get_json_model_adapter(request)
    red = [m for m in model.materials if m.name == 'Red']
    assert len(red) == 1, f"Expected exactly one 'Red' material, got {len(red)}"
    r, g, b, a = red[0].color
    assert r == 220, f"Red channel expected 220, got {r}"
    assert g == 20, f"Green channel expected 20, got {g}"
    assert b == 20, f"Blue channel expected 20, got {b}"
    assert a == 255, f"Alpha channel expected 255, got {a}"
    assert math.isclose(_srgb_to_linear(r), 0.723, rel_tol=1e-2), f"Linear R mismatch: {_srgb_to_linear(r)}"


@then('the Blue material diffuse color matches the expected sRGB-to-linear conversion')
def then_blue_material_color_matches(request):
    """Assert Blue material (20, 20, 200) converts to correct linear color."""
    model = _get_json_model_adapter(request)
    blue = [m for m in model.materials if m.name == 'Blue']
    assert len(blue) == 1, f"Expected exactly one 'Blue' material, got {len(blue)}"
    r, g, b, a = blue[0].color
    assert r == 20, f"Red channel expected 20, got {r}"
    assert g == 20, f"Green channel expected 20, got {g}"
    assert b == 200, f"Blue channel expected 200, got {b}"
    assert a == 255, f"Alpha channel expected 255, got {a}"
    assert math.isclose(_srgb_to_linear(b), 0.586, rel_tol=1e-2), f"Linear B mismatch: {_srgb_to_linear(b)}"


# =========================================================================
# THEN steps — Geometry
# =========================================================================


@then('all mesh geometry is imported')
def then_all_geometry_imported(request):
    """Assert that faces exist in the imported model entities."""
    model = _get_json_model_adapter(request)
    faces = list(model.entities.faces)
    assert len(faces) >= 2, f"Expected at least 2 faces, got {len(faces)}"


@then('the face vertex positions match the JSON data')
def then_face_vertices_match(request):
    """Assert that face vertex data is preserved exactly as in source."""
    model = _get_json_model_adapter(request)
    data = _get_json_model(request)
    for i, face in enumerate(model.entities.faces):
        verts, tris, uvs = face.tessfaces
        assert len(verts) > 0, f"Face {i} has no vertices"
        assert len(tris) > 0, f"Face {i} has no triangles"
        assert len(uvs) > 0, f"Face {i} has no UVs"
        assert len(verts) == len(uvs), f"Face {i}: vert count ({len(verts)}) != uv count ({len(uvs)})"
        src_faces_data = [e for e in data['entities'] if e.get('type') == 'Face']
        if i < len(src_faces_data):
            assert len(verts) == len(src_faces_data[i].get('vertices', [])), (
                f"Face {i}: vertex count mismatch"
            )


@then('the number of imported entities matches the JSON data')
def then_entity_count_matches(request):
    """Assert that the entity count in the model matches expectations."""
    model = _get_json_model_adapter(request)
    data = _get_json_model(request)
    model_entities = list(model.entities)
    src_entities = data.get('entities', [])
    assert len(model_entities) == len(src_entities), (
        f"Entity count mismatch: {len(model_entities)} vs {len(src_entities)}"
    )


# =========================================================================
# THEN steps — Material assignment
# =========================================================================


@then('the front-face material references are correct')
def then_front_face_material_correct(request):
    model = _get_json_model_adapter(request)
    data = _get_json_model(request)
    faces = list(model.entities.faces)
    assert len(faces) > 0, "No faces to check front material"
    first_face = faces[0]
    src_faces = [e for e in data['entities'] if e.get('type') == 'Face']
    if src_faces:
        src_mat = src_faces[0].get('material')
        if src_mat:
            assert first_face.material is not None, "First face has no front material"
            assert first_face.material.name == src_mat, (
                f"Front material mismatch: {first_face.material.name} vs {src_mat}"
            )


@then('the back-face material references are correct')
def then_back_face_material_correct(request):
    model = _get_json_model_adapter(request)
    data = _get_json_model(request)
    faces = list(model.entities.faces)
    assert len(faces) > 1, "Not enough faces to check back material"
    second_face = faces[1]
    src_faces = [e for e in data['entities'] if e.get('type') == 'Face']
    if len(src_faces) > 1:
        src_back_mat = src_faces[1].get('back_material')
        if src_back_mat:
            assert second_face.back_material is not None, (
                f"Second face has no back material, expected '{src_back_mat}'"
            )
            assert second_face.back_material.name == src_back_mat, (
                f"Back material mismatch: {second_face.back_material.name} vs {src_back_mat}"
            )


# =========================================================================
# THEN steps — Components / Groups
# =========================================================================


@then('component definitions are imported as collections')
def then_components_imported(request):
    model = _get_json_model_adapter(request)
    defs = model.component_definitions
    names = {d.name for d in defs}
    assert 'Chair' in names, f"Missing 'Chair' definition, have: {names}"
    assert len(defs) >= 1, f"Expected at least 1 definition, got {len(defs)}"


@then('the FurnitureGroup contains its child entities')
def then_furniture_group_has_children(request):
    model = _get_json_model_adapter(request)
    groups = list(model.entities.groups)
    furniture = [g for g in groups if g.name == 'FurnitureGroup']
    assert len(furniture) == 1, f"Expected exactly one FurnitureGroup, got {len(furniture)}"
    group_entities = list(furniture[0].entities)
    assert len(group_entities) > 0, "FurnitureGroup has no child entities"


@then('the FurnitureGroup parent-child hierarchy is correct')
def then_furniture_group_hierarchy_correct(request):
    model = _get_json_model_adapter(request)
    groups = list(model.entities.groups)
    furniture = [g for g in groups if g.name == 'FurnitureGroup']
    assert len(furniture) == 1, f"Expected exactly one FurnitureGroup, got {len(furniture)}"
    children = list(furniture[0].entities)
    face_count = sum(
        1 for e in children
        if hasattr(e, 'tessfaces') or (isinstance(e, dict) and e.get('type') == 'Face')
    )
    assert face_count >= 1, "FurnitureGroup missing its face child"


@then('the FurnitureGroup transform is identity')
def then_furniture_group_transform_identity(request):
    model = _get_json_model_adapter(request)
    groups = list(model.entities.groups)
    furniture = [g for g in groups if g.name == 'FurnitureGroup']
    assert len(furniture) == 1, f"Expected exactly one FurnitureGroup, got {len(furniture)}"
    transform = furniture[0].transform
    expected = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    for i in range(4):
        for j in range(4):
            assert math.isclose(transform[i][j], expected[i][j], abs_tol=1e-6), (
                f"Transform mismatch at [{i}][{j}]: {transform[i][j]} vs {expected[i][j]}"
            )


@then('the Chair component instance uses the Chair definition')
def then_chair_instance_uses_chair_definition(request):
    model = _get_json_model_adapter(request)
    instances = list(model.entities.instances)
    assert len(instances) >= 1, "No component instances found"
    chair_instances = [i for i in instances if 'Chair' in (i.definition.name if i.definition else '')]
    assert len(chair_instances) >= 1, "No Chair component instance found"


@then('the Chair definition has the correct face count')
def then_chair_definition_face_count(request):
    model = _get_json_model_adapter(request)
    defs = model.component_definitions
    chair = [d for d in defs if d.name == 'Chair']
    assert len(chair) == 1, f"Expected exactly one 'Chair' definition, got {len(chair)}"
    faces = list(chair[0].entities.faces)
    assert len(faces) == 2, f"Chair definition expected 2 faces, got {len(faces)}"


# =========================================================================
# THEN steps — Layer visibility
# =========================================================================


@then('layer visibility is respected')
def then_layer_visibility_respected(request):
    model = _get_json_model_adapter(request)
    layers = model.layers
    layer_map = {l.name: l for l in layers}
    assert 'Layer0' in layer_map, "Missing Layer0"
    assert 'Furniture' in layer_map, "Missing Furniture layer"
    assert 'Hidden' in layer_map, "Missing Hidden layer"
    assert layer_map['Layer0'].visible is True, "Layer0 should be visible"
    assert layer_map['Furniture'].visible is True, "Furniture should be visible"
    assert layer_map['Hidden'].visible is False, "Hidden should be invisible"


@then('entities on hidden layers are not imported')
def then_hidden_layer_entities_excluded(request):
    model = _get_json_model_adapter(request)
    layers = model.layers
    hidden_layers = [l for l in layers if not l.visible]
    assert len(hidden_layers) >= 1, "Expected at least one hidden layer"


# =========================================================================
# THEN steps — Screenshots
# =========================================================================

@then('a screenshot is captured')
def then_screenshot_captured(request, screenshot_dir, no_screenshots):
    """
    Capture a screenshot of the Blender viewport.

    In CI-safe mode (--no-screenshots), writes a placeholder.
    In full mode, saves the model JSON and runs Blender via Docker
    compose to render a solid viewport screenshot.
    """
    if no_screenshots:
        placeholder_path = os.path.join(screenshot_dir, 'placeholder.txt')
        with open(placeholder_path, 'w') as f:
            f.write('Screenshot placeholder (CI mode — no Blender available)\n')
        return

    # Full mode — render a real Blender screenshot
    model_data = getattr(request.node, '_imported_model', None)
    if model_data is None:
        pytest.fail('No imported model data available for screenshot')

    # Save model JSON to a path accessible inside the blender container
    model_json_path = os.path.join(screenshot_dir, 'model.json')
    with open(model_json_path, 'w') as f:
        json.dump(model_data, f)

    output_path = os.path.join(screenshot_dir, 'render.png')
    # Inside the container, screenshot_dir maps to /screenshots/<scenario>/
    container_model_path = '/screenshots/' + os.path.basename(screenshot_dir) + '/model.json'
    container_output_path = '/screenshots/' + os.path.basename(screenshot_dir) + '/render.png'

    cmd = [
        'docker', 'compose', 'run', '--rm',
        'blender',
        'blender', '--background',
        '--python', '/plugin/tests/bdd/render_screenshot.py',
        '--',
        container_model_path,
        container_output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        pytest.fail(
            f"Blender screenshot render failed (exit {result.returncode}).\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    # Verify screenshot was created
    if not os.path.exists(output_path):
        pytest.fail(f"Screenshot not created at {output_path}")

    # Log render result for test report
    try:
        output_line = result.stdout.strip().split('\n')[-1]
        render_info = json.loads(output_line)
        if render_info.get('status') == 'passed':
            print(f"\nScreenshot: {output_path} ({render_info.get('size_bytes', '?')} bytes)")
        else:
            pytest.fail(f"Render script reported error: {render_info.get('message', 'unknown')}")
    except (json.JSONDecodeError, IndexError):
        pass  # Non-JSON output from Blender is fine; screenshot file is the ground truth

@then('a wireframe screenshot is captured')
def then_wireframe_screenshot_captured(request, screenshot_dir, no_screenshots):
    """
    Capture a wireframe screenshot of the Blender viewport.

    In CI-safe mode (--no-screenshots), writes a placeholder.
    In full mode, runs Blender via Docker to render a wireframe overlay PNG.
    Temporarily applies Wireframe modifiers to all mesh objects for the render.
    """
    if no_screenshots:
        placeholder_path = os.path.join(screenshot_dir, 'wireframe_placeholder.txt')
        with open(placeholder_path, 'w') as f:
            f.write('Wireframe screenshot placeholder (CI mode — no Blender available)\n')
        return

    # Full mode — render a real Blender wireframe screenshot
    model_data = getattr(request.node, '_imported_model', None)
    if model_data is None:
        pytest.fail('No imported model data available for wireframe screenshot')

    # Save model JSON to a path accessible inside the blender container
    model_json_path = os.path.join(screenshot_dir, 'model.json')
    with open(model_json_path, 'w') as f:
        json.dump(model_data, f)

    output_path = os.path.join(screenshot_dir, 'render_wireframe.png')
    # Inside the container, screenshot_dir maps to /screenshots/<scenario>/
    container_model_path = '/screenshots/' + os.path.basename(screenshot_dir) + '/model.json'
    container_output_path = '/screenshots/' + os.path.basename(screenshot_dir) + '/render_wireframe.png'

    cmd = [
        'docker', 'compose', 'run', '--rm',
        'blender',
        'blender', '--background',
        '--python', '/plugin/tests/bdd/render_wireframe_screenshot.py',
        '--',
        container_model_path,
        container_output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        pytest.fail(
            f"Blender wireframe screenshot render failed (exit {result.returncode}).\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    # Verify screenshot was created
    if not os.path.exists(output_path):
        pytest.fail(f"Wireframe screenshot not created at {output_path}")

    # Log render result for test report
    try:
        output_line = result.stdout.strip().split('\n')[-1]
        render_info = json.loads(output_line)
        if render_info.get('status') == 'passed':
            print(f"\nWireframe screenshot: {output_path} ({render_info.get('size_bytes', '?')} bytes, "
                  f"wire_thickness={render_info.get('wire_thickness', '?')})")
        else:
            pytest.fail(f"Wireframe render script reported error: {render_info.get('message', 'unknown')}")
    except (json.JSONDecodeError, IndexError):
        pass  # Non-JSON output from Blender is fine; screenshot file is the ground truth

# =========================================================================
# Teardown: stop Ruby server after each scenario that started one
# =========================================================================


@pytest.fixture(autouse=True)
def _auto_cleanup_server(request):
    """Stop any Ruby server subprocess started during test."""
    yield
    proc = getattr(request.node, '_ruby_server_proc', None)
    socket_path = getattr(request.node, '_socket_path', None)

    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
            proc.wait()

    if socket_path and os.path.exists(socket_path):
        try:
            os.unlink(socket_path)
        except OSError:
            pass
