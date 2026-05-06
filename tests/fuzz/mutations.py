"""
MutationStrategy classes for fuzzing the SketchUp live sync pipeline.

Each strategy applies a mutation to the SketchUp model via the Remote Control
API (/control/* endpoints) and returns a dict describing the mutation result.

Strategies can run in two modes:
    --fuzz-mock: POST against the Ruby mock server (returns canned responses)
    --fuzz-real: POST against the real SketchUp VM (TCP mode)

The Remote Control API uses meters for all spatial coordinates,
matching the serialization convention.
"""

import http.client
import json
import math
import os
import random
import socket
import tempfile
import time


# ------------------------------------------------------------------
# HTTP helpers
# ------------------------------------------------------------------


class _UnixSocketHTTPConnection(http.client.HTTPConnection):
    """HTTP/1.1 connection over a Unix domain socket."""

    def __init__(self, path):
        super().__init__("localhost")
        self._path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(self._path)
        self.sock = s


def _post_control(socket_path, control_path, body):
    """POST JSON body to a /control/* endpoint via Unix socket.

    Returns (status_code, response_dict).
    """
    conn = _UnixSocketHTTPConnection(socket_path)
    try:
        json_body = json.dumps(body) if body is not None else ""
        conn.request("POST", control_path, body=json_body,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = json.loads(resp.read())
        return resp.status, data
    finally:
        conn.close()


def _post_control_tcp(host, port, control_path, body):
    """POST JSON body to a /control/* endpoint via TCP.

    Returns (status_code, response_dict).
    """
    conn = http.client.HTTPConnection(host, port, timeout=10)
    try:
        json_body = json.dumps(body) if body is not None else ""
        conn.request("POST", control_path, body=json_body,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = json.loads(resp.read())
        return resp.status, data
    finally:
        conn.close()


def _fetch_model(socket_path):
    """GET /model and return the parsed JSON dict."""
    conn = _UnixSocketHTTPConnection(socket_path)
    try:
        conn.request("GET", "/model")
        resp = conn.getresponse()
        if resp.status != 200:
            raise RuntimeError(f"GET /model returned HTTP {resp.status}")
        return json.loads(resp.read())
    finally:
        conn.close()


def _fetch_model_tcp(host, port):
    """GET /model over TCP and return the parsed JSON dict."""
    conn = http.client.HTTPConnection(host, port, timeout=10)
    try:
        conn.request("GET", "/model")
        resp = conn.getresponse()
        if resp.status != 200:
            raise RuntimeError(f"GET /model returned HTTP {resp.status}")
        return json.loads(resp.read())
    finally:
        conn.close()


# ------------------------------------------------------------------
# Random helpers
# ------------------------------------------------------------------


def _random_point(min_v=-5.0, max_v=5.0):
    """Return a random 3D point in meters."""
    return [round(random.uniform(min_v, max_v), 4) for _ in range(3)]


def _random_polygon(min_v=-3.0, max_v=3.0, n=4):
    """Return a random polygon with n vertices as a flat list of [x,y,z,...]."""
    points = []
    for _ in range(n):
        points.append([round(random.uniform(min_v, max_v), 4),
                       round(random.uniform(min_v, max_v), 4),
                       round(random.uniform(-0.5, 0.5), 4)])
    return points


def _random_translation(max_offset=2.0):
    """Return a random translation as a 16-element row-major identity matrix
    with random translation components."""
    tx = round(random.uniform(-max_offset, max_offset), 4)
    ty = round(random.uniform(-max_offset, max_offset), 4)
    tz = round(random.uniform(-max_offset, max_offset), 4)
    return [1, 0, 0, tx,
            0, 1, 0, ty,
            0, 0, 1, tz,
            0, 0, 0, 1]


# ------------------------------------------------------------------
# MutationStrategy base
# ------------------------------------------------------------------


class MutationStrategy:
    """Base class for mutation strategies.

    Subclasses must implement:
        name (class attribute) — human-readable name
        description (class attribute) — what the strategy does
        apply(self, host, port, socket_path) -> dict — apply the mutation
    """

    name = ""
    description = ""

    def __init__(self, host="127.0.0.1", port=9876, socket_path=None):
        self.host = host
        self.port = port
        self.socket_path = socket_path

    def _post(self, control_path, body):
        """POST to /control/*, auto-selecting Unix socket or TCP mode."""
        if self.socket_path:
            return _post_control(self.socket_path, f"/control/{control_path}", body)
        return _post_control_tcp(self.host, self.port, f"/control/{control_path}", body)

    def _fetch_model(self):
        """Fetch the current model JSON."""
        if self.socket_path:
            return _fetch_model(self.socket_path)
        return _fetch_model_tcp(self.host, self.port)

    def apply(self):
        """Apply the mutation and return a dict with mutation result info.

        Must return a dict with at least:
            {'strategy': self.name, 'params': {...}, 'status': int, 'response': {...}}
        """
        raise NotImplementedError

    def __repr__(self):
        return f"<{self.__class__.__name__}>"


# ------------------------------------------------------------------
# Built-in strategies
# ------------------------------------------------------------------


class AddFaceMutation(MutationStrategy):
    """POST /control/geometry/face with a random polygon."""

    name = "add_face"
    description = "Add a random face to the model"

    def apply(self):
        points = _random_polygon()
        params = {"points": points}
        status, response = self._post("geometry/face", params)
        return {
            "strategy": self.name,
            "params": params,
            "status": status,
            "response": response,
        }


class DeleteEntityMutation(MutationStrategy):
    """POST /control/geometry/delete on a known entity from the model.

    Requires a fetch first to find an entity persistent_id.
    """

    name = "delete_entity"
    description = "Delete a random entity from the model"

    def apply(self):
        model = self._fetch_model()
        entities = model.get("entities", [])
        if not entities:
            return {
                "strategy": self.name,
                "params": {},
                "status": 400,
                "response": {"error": "no entities to delete"},
                "skipped": True,
            }
        target = random.choice(entities)
        pid = target.get("persistent_id")
        params = {"persistent_id": pid}
        status, response = self._post("geometry/delete", params)
        return {
            "strategy": self.name,
            "params": params,
            "status": status,
            "response": response,
        }


class MoveGroupMutation(MutationStrategy):
    """POST /control/geometry/transform with a random translation on a group.

    Finds the first Group in the model and applies a random translation.
    """

    name = "move_group"
    description = "Apply random translation to a group"

    def apply(self):
        model = self._fetch_model()
        entities = model.get("entities", [])
        groups = [e for e in entities if e.get("type") == "Group"]
        if not groups:
            return {
                "strategy": self.name,
                "params": {},
                "status": 400,
                "response": {"error": "no groups to move"},
                "skipped": True,
            }
        target = random.choice(groups)
        pid = target.get("persistent_id")
        transform = _random_translation()
        params = {"persistent_id": pid, "transformation": transform}
        status, response = self._post("geometry/transform", params)
        return {
            "strategy": self.name,
            "params": params,
            "status": status,
            "response": response,
        }


class ChangeMaterialMutation(MutationStrategy):
    """POST /control/material with a random RGB color on an existing material."""

    name = "change_material"
    description = "Change a material's color to a random RGB"

    def apply(self):
        model = self._fetch_model()
        materials = model.get("materials", [])
        if not materials:
            return {
                "strategy": self.name,
                "params": {},
                "status": 400,
                "response": {"error": "no materials to change"},
                "skipped": True,
            }
        target = random.choice(materials)
        name = target.get("name", "Unnamed")
        color = {"r": random.randint(0, 255),
                 "g": random.randint(0, 255),
                 "b": random.randint(0, 255)}
        params = {"name": name, "color": color}
        status, response = self._post("material", params)
        return {
            "strategy": self.name,
            "params": params,
            "status": status,
            "response": response,
        }


class ToggleLayerMutation(MutationStrategy):
    """POST /control/layer toggling visibility of a random layer."""

    name = "toggle_layer"
    description = "Toggle layer visibility"

    def apply(self):
        model = self._fetch_model()
        layers = model.get("layers", [])
        if not layers:
            return {
                "strategy": self.name,
                "params": {},
                "status": 400,
                "response": {"error": "no layers to toggle"},
                "skipped": True,
            }
        target = random.choice(layers)
        name = target.get("name", "Unnamed")
        current_visible = target.get("visible", True)
        params = {"name": name, "visible": not current_visible}
        status, response = self._post("layer", params)
        return {
            "strategy": self.name,
            "params": params,
            "status": status,
            "response": response,
        }


class AddComponentMutation(MutationStrategy):
    """POST /control/geometry/component using an existing definition."""

    name = "add_component"
    description = "Add a new component instance from an existing definition"

    def apply(self):
        model = self._fetch_model()
        defs = model.get("component_definitions", {})
        if not defs:
            return {
                "strategy": self.name,
                "params": {},
                "status": 400,
                "response": {"error": "no component definitions available"},
                "skipped": True,
            }
        def_name = random.choice(list(defs.keys()))
        params = {"definition_name": def_name}
        status, response = self._post("geometry/component", params)
        return {
            "strategy": self.name,
            "params": params,
            "status": status,
            "response": response,
        }


class DeleteMaterialMutation(MutationStrategy):
    """POST /control/material/delete to remove a material, then re-add it.

    This is a two-step mutation: delete then re-create, testing that the
    plugin handles material deletion without crashing and that re-adding
    restores state correctly.
    """

    name = "delete_material"
    description = "Delete a material and re-add it"

    def apply(self):
        model = self._fetch_model()
        materials = model.get("materials", [])
        if not materials:
            return {
                "strategy": self.name,
                "params": {},
                "status": 400,
                "response": {"error": "no materials to delete"},
                "skipped": True,
            }
        target = random.choice(materials)
        name = target.get("name", "Unnamed")
        color = target.get("color", {"r": 128, "g": 128, "b": 128})
        opacity = target.get("opacity", 1.0)

        # Delete
        del_params = {"name": name}
        del_status, del_response = self._post("material/delete", del_params)
        if del_status != 200:
            return {
                "strategy": self.name,
                "params": {"phase": "delete", "body": del_params},
                "status": del_status,
                "response": del_response,
            }

        # Brief pause to let the model stabilize
        time.sleep(0.1)

        # Re-add
        add_params = {"name": name, "color": color, "opacity": opacity}
        add_status, add_response = self._post("material", add_params)
        return {
            "strategy": self.name,
            "params": {"phase": "full", "delete": del_params, "add": add_params},
            "status": add_status,
            "response": add_response,
        }


class CompositeMutation(MutationStrategy):
    """Applies N sub-mutations in sequence.

    Sub-mutations are chosen randomly from the given pool.
    """

    name = "composite"
    description = "Apply multiple random mutations in sequence"

    def __init__(self, strategies, count=3, **kwargs):
        super().__init__(**kwargs)
        self._strategies = strategies
        self._count = count

    def apply(self):
        chosen = random.choices(self._strategies, k=self._count)
        results = []
        for strategy_cls in chosen:
            inst = strategy_cls(
                host=self.host, port=self.port, socket_path=self.socket_path
            )
            result = inst.apply()
            results.append(result)
            time.sleep(0.05)
        return {
            "strategy": self.name,
            "params": {"count": self._count, "sub_strategies": [c.name for c in chosen]},
            "status": 200,
            "response": {"results": results},
        }


class StressSequence(MutationStrategy):
    """Applies 20+ random mutations rapidly to stress-test the pipeline."""

    name = "stress_sequence"
    description = "Apply 20+ rapid random mutations"

    def __init__(self, strategies, count=25, **kwargs):
        super().__init__(**kwargs)
        self._strategies = strategies
        self._count = count

    def apply(self):
        chosen = [random.choice(self._strategies) for _ in range(self._count)]
        results = []
        for strategy_cls in chosen:
            inst = strategy_cls(
                host=self.host, port=self.port, socket_path=self.socket_path
            )
            result = inst.apply()
            results.append(result)
        return {
            "strategy": self.name,
            "params": {"count": self._count},
            "status": 200,
            "response": {"results": results, "failed": sum(1 for r in results if r.get("status", 200) >= 400)},
        }


# ------------------------------------------------------------------
# Registry of all strategies (for parametrized test discovery)
# ------------------------------------------------------------------

def all_strategies(host="127.0.0.1", port=9876, socket_path=None):
    """Return a list of (name, strategy_instance) for all built-in strategies.

    CompositeMutation and StressSequence wrap the individual strategies,
    so they are constructed with the strategy list.
    """
    base_kwargs = {"host": host, "port": port, "socket_path": socket_path}
    individuals = [
        AddFaceMutation(**base_kwargs),
        DeleteEntityMutation(**base_kwargs),
        MoveGroupMutation(**base_kwargs),
        ChangeMaterialMutation(**base_kwargs),
        ToggleLayerMutation(**base_kwargs),
        AddComponentMutation(**base_kwargs),
        DeleteMaterialMutation(**base_kwargs),
    ]
    strategy_classes = [
        AddFaceMutation, DeleteEntityMutation, MoveGroupMutation,
        ChangeMaterialMutation, ToggleLayerMutation, AddComponentMutation,
        DeleteMaterialMutation,
    ]
    composite = CompositeMutation(
        strategy_classes,
        count=3, **base_kwargs
    )
    stress = StressSequence(strategy_classes, count=25, **base_kwargs)
    return individuals + [composite, stress]