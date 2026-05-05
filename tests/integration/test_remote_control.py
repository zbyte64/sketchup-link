"""
tests/integration/test_remote_control.py

Integration tests for the remote control HTTP API.

These tests hit the Ruby mock server (server.rb) which returns canned
responses matching the real API contract. No SketchUp is involved.

The mock server's /control/* handlers validate required fields and
return realistic response shapes, so we can test the HTTP contract,
error handling, and response parsing independently.
"""

import http.client
import json
import os
import socket

import pytest

from conftest import _UnixSocketHTTPConnection


# ---------------------------------------------------------------------------
# Helper: POST JSON to a control endpoint
# ---------------------------------------------------------------------------

def _post(socket_path, path, body=None):
    """POST JSON body to a /control/* endpoint, return (status, data)."""
    conn = _UnixSocketHTTPConnection(socket_path)
    try:
        json_body = json.dumps(body) if body is not None else ''
        conn.request('POST', path, body=json_body,
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        data = json.loads(resp.read())
        return resp.status, data
    finally:
        conn.close()


# ===========================================================================
# Camera
# ===========================================================================

class TestRemoteControlCamera:
    def test_set_camera_position(self, ruby_server):
        status, data = _post(ruby_server, '/control/camera', {
            'eye': [0.0, 0.0, 5.0],
            'target': [0.0, 0.0, 0.0],
            'up': [0.0, 1.0, 0.0],
        })
        assert status == 200
        assert data == {'ok': True}

    def test_set_camera_with_fov(self, ruby_server):
        status, data = _post(ruby_server, '/control/camera', {
            'eye': [1.0, 2.0, 3.0],
            'target': [0.0, 0.0, 0.0],
            'up': [0.0, 0.0, 1.0],
            'fov': 45.0,
            'perspective': True,
        })
        assert status == 200
        assert data == {'ok': True}

    def test_set_camera_missing_eye(self, ruby_server):
        status, data = _post(ruby_server, '/control/camera', {
            'target': [0.0, 0.0, 0.0],
            'up': [0.0, 1.0, 0.0],
        })
        assert status == 400
        assert data['error'].startswith('missing required field')

    def test_zoom_camera(self, ruby_server):
        status, data = _post(ruby_server, '/control/camera/zoom', {
            'factor': 1.5,
        })
        assert status == 200
        assert data == {'ok': True}

    def test_zoom_camera_missing_factor(self, ruby_server):
        status, data = _post(ruby_server, '/control/camera/zoom', {})
        assert status == 400
        assert 'factor' in data['error']


# ===========================================================================
# Layers
# ===========================================================================

class TestRemoteControlLayer:
    def test_set_layer_visible(self, ruby_server):
        status, data = _post(ruby_server, '/control/layer', {
            'name': 'TestLayer',
            'visible': True,
        })
        assert status == 200
        assert data == {'ok': True}

    def test_set_layer_hidden(self, ruby_server):
        status, data = _post(ruby_server, '/control/layer', {
            'name': 'HiddenLayer',
            'visible': False,
        })
        assert status == 200
        assert data == {'ok': True}

    def test_set_layer_missing_name(self, ruby_server):
        status, data = _post(ruby_server, '/control/layer', {
            'visible': True,
        })
        assert status == 400
        assert 'name' in data['error']

    def test_set_layer_without_visible_defaults_ok(self, ruby_server):
        status, data = _post(ruby_server, '/control/layer', {
            'name': 'DefaultLayer',
        })
        assert status == 200
        assert data == {'ok': True}


# ===========================================================================
# Plugins
# ===========================================================================

class TestRemoteControlPlugin:
    def test_enable_plugin(self, ruby_server):
        status, data = _post(ruby_server, '/control/plugin', {
            'name': 'SketchUp Link',
            'enabled': True,
        })
        assert status == 200
        assert data['ok'] is True
        assert 'note' in data

    def test_disable_plugin(self, ruby_server):
        status, data = _post(ruby_server, '/control/plugin', {
            'name': 'Test Extension',
            'enabled': False,
        })
        assert status == 200
        assert data['ok'] is True

    def test_toggle_missing_name(self, ruby_server):
        status, data = _post(ruby_server, '/control/plugin', {
            'enabled': True,
        })
        assert status == 400
        assert 'name' in data['error']

    def test_toggle_missing_enabled(self, ruby_server):
        status, data = _post(ruby_server, '/control/plugin', {
            'name': 'Something',
        })
        assert status == 400
        assert 'enabled' in data['error']

    def test_nonexistent_plugin_returns_404(self, ruby_server):
        status, data = _post(ruby_server, '/control/plugin', {
            'name': 'NonExistentExtension',
            'enabled': True,
        })
        assert status == 404
        assert 'not found' in data['error']


# ===========================================================================
# Textures
# ===========================================================================

class TestRemoteControlTexture:
    def test_load_texture(self, ruby_server):
        # Use an existing file in the repo for the mock check
        status, data = _post(ruby_server, '/control/texture', {
            'material_name': 'Wood',
            'file_path': __file__,
        })
        assert status == 200
        assert data['ok'] is True
        assert data['material']['name'] == 'Wood'
        assert data['material']['texture'] == __file__

    def test_load_texture_missing_material_name(self, ruby_server):
        status, data = _post(ruby_server, '/control/texture', {
            'file_path': '/tmp/test.png',
        })
        assert status == 400
        assert 'material_name' in data['error']

    def test_load_texture_missing_file_path(self, ruby_server):
        status, data = _post(ruby_server, '/control/texture', {
            'material_name': 'Wood',
        })
        assert status == 400
        assert 'file_path' in data['error']

    def test_load_texture_nonexistent_file(self, ruby_server):
        status, data = _post(ruby_server, '/control/texture', {
            'material_name': 'Wood',
            'file_path': '/tmp/nonexistent_texture_xyz.png',
        })
        assert status == 400
        assert 'not found' in data['error']


# ===========================================================================
# Materials
# ===========================================================================

class TestRemoteControlMaterial:
    def test_create_material(self, ruby_server):
        status, data = _post(ruby_server, '/control/material', {
            'name': 'Red',
            'color': {'r': 220, 'g': 20, 'b': 20},
            'opacity': 1.0,
        })
        assert status == 200
        assert data == {'ok': True}

    def test_update_material_color(self, ruby_server):
        status, data = _post(ruby_server, '/control/material', {
            'name': 'Red',
            'color': {'r': 255, 'g': 0, 'b': 0},
        })
        assert status == 200
        assert data == {'ok': True}

    def test_create_material_minimal(self, ruby_server):
        status, data = _post(ruby_server, '/control/material', {
            'name': 'Blue',
        })
        assert status == 200
        assert data == {'ok': True}

    def test_material_missing_name(self, ruby_server):
        status, data = _post(ruby_server, '/control/material', {
            'color': {'r': 220, 'g': 20, 'b': 20},
        })
        assert status == 400
        assert 'name' in data['error']

    def test_delete_material(self, ruby_server):
        status, data = _post(ruby_server, '/control/material/delete', {
            'name': 'Red',
        })
        assert status == 200
        assert data == {'ok': True}

    def test_delete_material_missing_name(self, ruby_server):
        status, data = _post(ruby_server, '/control/material/delete', {})
        assert status == 400
        assert 'name' in data['error']


# ===========================================================================
# Geometry
# ===========================================================================

class TestRemoteControlGeometry:
    def test_add_face(self, ruby_server):
        status, data = _post(ruby_server, '/control/geometry/face', {
            'points': [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
            'material': 'Red',
            'layer': 'Layer0',
        })
        assert status == 200
        assert data['ok'] is True
        assert isinstance(data['persistent_id'], int)

    def test_add_face_missing_points(self, ruby_server):
        status, data = _post(ruby_server, '/control/geometry/face', {
            'material': 'Red',
        })
        assert status == 400
        assert 'points' in data['error']

    def test_add_edge(self, ruby_server):
        status, data = _post(ruby_server, '/control/geometry/edge', {
            'start': [0, 0, 0],
            'end': [1, 1, 0],
            'layer': 'Layer0',
        })
        assert status == 200
        assert data['ok'] is True
        assert isinstance(data['persistent_id'], int)

    def test_add_edge_missing_start(self, ruby_server):
        status, data = _post(ruby_server, '/control/geometry/edge', {
            'end': [1, 1, 0],
        })
        assert status == 400
        assert 'start' in data['error']

    def test_add_edge_missing_end(self, ruby_server):
        status, data = _post(ruby_server, '/control/geometry/edge', {
            'start': [0, 0, 0],
        })
        assert status == 400
        assert 'end' in data['error']

    def test_add_group(self, ruby_server):
        status, data = _post(ruby_server, '/control/geometry/group', {
            'name': 'TestGroup',
            'layer': 'Layer0',
        })
        assert status == 200
        assert data['ok'] is True
        assert isinstance(data['persistent_id'], int)

    def test_add_group_with_transform(self, ruby_server):
        status, data = _post(ruby_server, '/control/geometry/group', {
            'name': 'TransformedGroup',
            'layer': 'Layer0',
            'transformation': [
                1, 0, 0, 2.0,
                0, 1, 0, 0.5,
                0, 0, 1, 0,
                0, 0, 0, 1,
            ],
        })
        assert status == 200
        assert data['ok'] is True

    def test_add_component(self, ruby_server):
        status, data = _post(ruby_server, '/control/geometry/component', {
            'definition_name': 'Chair',
            'layer': 'Furniture',
        })
        assert status == 200
        assert data['ok'] is True
        assert isinstance(data['persistent_id'], int)

    def test_add_component_missing_definition_name(self, ruby_server):
        status, data = _post(ruby_server, '/control/geometry/component', {
            'layer': 'Furniture',
        })
        assert status == 400
        assert 'definition_name' in data['error']

    def test_delete_entity(self, ruby_server):
        status, data = _post(ruby_server, '/control/geometry/delete', {
            'persistent_id': 12345,
        })
        assert status == 200
        assert data == {'ok': True}

    def test_delete_entity_missing_pid(self, ruby_server):
        status, data = _post(ruby_server, '/control/geometry/delete', {})
        assert status == 400
        assert 'persistent_id' in data['error']

    def test_transform_entity(self, ruby_server):
        status, data = _post(ruby_server, '/control/geometry/transform', {
            'persistent_id': 12345,
            'transformation': [
                1, 0, 0, 0,
                0, 1, 0, 0,
                0, 0, 1, 0,
                0, 0, 0, 1,
            ],
        })
        assert status == 200
        assert data == {'ok': True}

    def test_transform_entity_missing_pid(self, ruby_server):
        status, data = _post(ruby_server, '/control/geometry/transform', {
            'transformation': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        })
        assert status == 400
        assert 'persistent_id' in data['error']

    def test_transform_entity_missing_transform(self, ruby_server):
        status, data = _post(ruby_server, '/control/geometry/transform', {
            'persistent_id': 12345,
        })
        assert status == 400
        assert 'transformation' in data['error']


# ===========================================================================
# Model
# ===========================================================================

class TestRemoteControlModel:
    def test_clear_model(self, ruby_server):
        status, data = _post(ruby_server, '/control/model/clear', {})
        assert status == 200
        assert data == {'ok': True}

    def test_new_model(self, ruby_server):
        status, data = _post(ruby_server, '/control/model/new', {})
        assert status == 200
        assert data == {'ok': True}


# ===========================================================================
# Error Handling
# ===========================================================================

class TestRemoteControlErrors:
    def test_empty_body(self, ruby_server):
        status, data = _post(ruby_server, '/control/layer', None)
        assert status == 400
        assert 'name' in data['error']

    def test_empty_object_body(self, ruby_server):
        status, data = _post(ruby_server, '/control/layer', {})
        assert status == 400
        assert 'name' in data['error']

    def test_bad_route_returns_404(self, ruby_server):
        status, data = _post(ruby_server, '/control/nonexistent/route', {})
        assert status == 404
        assert 'error' in data

    def test_get_on_control_path_returns_404(self, ruby_server):
        conn = _UnixSocketHTTPConnection(ruby_server)
        try:
            conn.request('GET', '/control/camera')
            resp = conn.getresponse()
            data = json.loads(resp.read())
            assert resp.status == 404
        finally:
            conn.close()

    def test_invalid_json_is_400(self, ruby_server):
        """Send non-JSON body and expect 400."""
        conn = _UnixSocketHTTPConnection(ruby_server)
        try:
            conn.request('POST', '/control/camera',
                         body='not valid json{{{',
                         headers={'Content-Type': 'application/json'})
            resp = conn.getresponse()
            data = json.loads(resp.read())
            assert resp.status == 400
            assert 'invalid JSON' in data['error']
        finally:
            conn.close()
