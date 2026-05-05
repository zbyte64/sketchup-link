"""
live_adapter.py — Duck-typed wrappers that present a JSON model snapshot
(fetched from the sketchup-link Unix domain socket) as the same interface
that SceneImporter.load() expects from the Cython SLAPI bindings.

Transport: HTTP/1.1 over a Unix domain socket (AF_UNIX).
  - macOS/Linux: /tmp/sketchup-link.sock
  - Windows 11:  %TEMP%\\sketchup-link.sock
"""

import http.client
import json
import os
import socket
import tempfile


# ---------------------------------------------------------------------------
# Socket path — platform-aware, matches sketchup_link/constants.rb
# ---------------------------------------------------------------------------

DEFAULT_SOCKET_PATH = os.path.join(tempfile.gettempdir(), "sketchup-link.sock")

TCP_DEFAULT_HOST = "127.0.0.1"
TCP_DEFAULT_PORT = 9876

# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

class _UnixSocketHTTPConnection(http.client.HTTPConnection):
    """HTTP/1.1 connection that connects via a Unix domain socket."""

    def __init__(self, socket_path):
        super().__init__("localhost")
        self._socket_path = socket_path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(self._socket_path)
        self.sock = s


def fetch_model_json(socket_path=DEFAULT_SOCKET_PATH):
    """GET /model over the Unix socket. Returns the parsed JSON dict."""
    conn = _UnixSocketHTTPConnection(socket_path)
    try:
        conn.request("GET", "/model")
        resp = conn.getresponse()
        if resp.status != 200:
            raise RuntimeError(f"sketchup-link returned HTTP {resp.status}")
        return json.loads(resp.read())
    finally:
        conn.close()

def fetch_model_json_tcp(host=TCP_DEFAULT_HOST, port=TCP_DEFAULT_PORT):
    """GET /model over TCP/IP. Returns the parsed JSON dict."""
    conn = http.client.HTTPConnection(host, port)
    try:
        conn.request("GET", "/model")
        resp = conn.getresponse()
        if resp.status != 200:
            raise RuntimeError(f"sketchup-link returned HTTP {resp.status}")
        return json.loads(resp.read())
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _NameOnly:
    """Minimal stub with just a .name — used for material/layer name refs."""

    def __init__(self, name):
        self.name = name


class JsonLayer:
    """Wraps a layer dict. Supports equality by name (for layers_skip checks)."""

    def __init__(self, d):
        self._d = d

    @property
    def name(self):
        return self._d.get("name", "")

    @property
    def visible(self):
        return self._d.get("visible", True)

    def __eq__(self, other):
        if isinstance(other, JsonLayer):
            return self.name == other.name
        return NotImplemented

    def __hash__(self):
        return hash(self.name)


# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------

class _JsonTexture:
    """Wraps a texture dict with .name, .dimensions, and .write(path).

    Matches the interface expected by SceneImporter.write_materials().
    """

    def __init__(self, d):
        self._d = d

    @property
    def name(self):
        return self._d.get("filename", "texture.png")

    @property
    def dimensions(self):
        # (width_px, height_px, width_m, height_m) — matching Cython Texture.dimensions
        return (
            self._d.get("image_width", 0),
            self._d.get("image_height", 0),
            self._d.get("width", 1.0),
            self._d.get("height", 1.0),
        )

    def write(self, path):
        import base64
        data = self._d.get("data", "")
        if data:
            with open(path, "wb") as f:
                f.write(base64.b64decode(data))


class _JsonColor:
    """Iterable (r, g, b, a) — supports `r, g, b, a = mat.color` unpacking."""

    def __init__(self, d):
        self._d = d

    def __iter__(self):
        yield self._d.get("r", 0)
        yield self._d.get("g", 0)
        yield self._d.get("b", 0)
        yield self._d.get("a", 255)


class JsonMaterial:
    """Wraps a material dict."""

    def __init__(self, d):
        self._d = d

    @property
    def name(self):
        return self._d.get("name", "")

    @property
    def color(self):
        return _JsonColor(self._d.get("color", {}))

    @property
    def opacity(self):
        return self._d.get("opacity", 1.0)

    @property
    def texture(self):
        d = self._d.get("texture")
        if d:
            return _JsonTexture(d)
        return None


# ---------------------------------------------------------------------------
# Face / Edge
# ---------------------------------------------------------------------------

class _JsonEdge:
    """Minimal edge stub — no smooth data in the JSON snapshot."""

    def GetSmooth(self):  # noqa: N802 — matches Cython method name
        return False


class JsonFace:
    """
    Wraps a face dict. Provides the tessfaces tuple that write_mesh_data()
    consumes: (vertices_list, triangles_list, uvs_list).

    Ruby already emits metres and normalised UVs so no conversion is needed
    here.
    """

    def __init__(self, d):
        self._d = d

    @property
    def material(self):
        name = self._d.get("material")
        return _NameOnly(name) if name else None

    @property
    def back_material(self):
        name = self._d.get("back_material")
        return _NameOnly(name) if name else None

    @property
    def tessfaces(self):
        verts = [tuple(v) for v in self._d.get("vertices", [])]
        tris  = [tuple(t) for t in self._d.get("triangles", [])]
        uvs   = [tuple(u) for u in self._d.get("uvs", [])]
        return (verts, tris, uvs)

    @property
    def st_scale(self):
        return (1.0, 1.0)

    @st_scale.setter
    def st_scale(self, value):
        pass  # write_mesh_data() may set this; no-op for live data

    @property
    def edges(self):
        # No edge data in the JSON snapshot; write_mesh_data() iterates this
        # only to check smoothing, so an empty list is a safe fallback.
        return []


# ---------------------------------------------------------------------------
# Entities container
# ---------------------------------------------------------------------------

class JsonEntities:
    """
    Wraps the entities list from the JSON. Exposes .faces, .groups,
    .instances iterables that match the Cython Entities interface.
    """

    def __init__(self, entities_list):
        self._list = entities_list

    @property
    def faces(self):
        return [JsonFace(e) for e in self._list if e.get("type") == "Face"]

    @property
    def groups(self):
        return [JsonGroup(e) for e in self._list if e.get("type") == "Group"]

    @property
    def instances(self):
        return [JsonInstance(e) for e in self._list if e.get("type") == "ComponentInstance"]

    def __iter__(self):
        return iter(self._list)


# ---------------------------------------------------------------------------
# Group / Instance
# ---------------------------------------------------------------------------

def _flat_to_4x4(flat):
    """Convert a 16-element row-major flat list to a 4×4 list-of-lists.
    Blender's Matrix() constructor requires a sequence of rows, not a flat list.
    """
    if flat is None:
        flat = [1, 0, 0, 0,  0, 1, 0, 0,  0, 0, 1, 0,  0, 0, 0, 1]
    return [flat[0:4], flat[4:8], flat[8:12], flat[12:16]]


class JsonGroup:
    def __init__(self, d):
        self._d = d

    @property
    def name(self):
        return self._d.get("name", "")

    @property
    def layer(self):
        layer_name = self._d.get("layer")
        return JsonLayer({"name": layer_name}) if layer_name else None

    @property
    def material(self):
        name = self._d.get("material")
        return _NameOnly(name) if name else None

    @property
    def transform(self):
        return _flat_to_4x4(self._d.get("transformation"))

    @property
    def hidden(self):
        return self._d.get("hidden", False)

    @property
    def entities(self):
        return JsonEntities(self._d.get("entities", []))


class JsonInstance:
    def __init__(self, d):
        self._d = d

    @property
    def name(self):
        return self._d.get("name", "")

    @property
    def layer(self):
        layer_name = self._d.get("layer")
        return JsonLayer({"name": layer_name}) if layer_name else None

    @property
    def material(self):
        name = self._d.get("material")
        return _NameOnly(name) if name else None

    @property
    def transform(self):
        return _flat_to_4x4(self._d.get("transformation"))

    @property
    def hidden(self):
        return self._d.get("hidden", False)

    @property
    def definition(self):
        return _NameOnly(self._d.get("definition_name", ""))


# ---------------------------------------------------------------------------
# Component definition
# ---------------------------------------------------------------------------

class JsonDefinitionRef:
    """
    Wraps a component definition dict.

    Exposes .name, .entities, .numInstances, .numUsedInstances (camelCase
    matching the Cython interface used in load() lines 258–261).
    """

    def __init__(self, d):
        self._d = d

    @property
    def name(self):
        return self._d.get("name", "")

    @property
    def entities(self):
        return JsonEntities(self._d.get("entities", []))

    @property
    def numInstances(self):  # noqa: N802
        return self._d.get("num_instances", 0)

    @property
    def numUsedInstances(self):  # noqa: N802
        return self._d.get("num_used_instances", 0)


# ---------------------------------------------------------------------------
# Camera (safe defaults — live import skips camera by default)
# ---------------------------------------------------------------------------

class JsonCamera:
    """
    Wraps a camera dict from the JSON model snapshot.

    When no camera data is present (backward compat with old servers or
    SketchUp without active model), safe defaults are returned.
    """

    def __init__(self, d=None):
        self._d = d or {}

    @classmethod
    def default(cls):
        """Safe defaults when no camera data is available."""
        return cls({})

    def GetOrientation(self):  # noqa: N802
        eye    = tuple(self._d.get("eye", (0, 0, 0)))
        target = tuple(self._d.get("target", (0, 0, 1)))
        up     = tuple(self._d.get("up", (0, 0, 1)))
        return eye, target, up

    @property
    def aspect_ratio(self):
        val = self._d.get("aspect_ratio", False)
        return val if val is not None else False

    @property
    def fov(self):
        return self._d.get("fov", 35.0)

    @property
    def perspective(self):
        return self._d.get("perspective", True)
# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class JsonModel:
    """
    Top-level model adapter. Wraps the GET /model JSON response and exposes
    the same interface as sketchup.Model (the Cython SLAPI binding).
    """

    def __init__(self, d):
        self._d = d

    @property
    def entities(self):
        return JsonEntities(self._d.get("entities", []))

    @property
    def materials(self):
        return [JsonMaterial(m) for m in self._d.get("materials", [])]

    @property
    def component_definition_as_dict(self):
        """Dict[name → JsonDefinitionRef] matching component_definition_as_dict."""
        return {
            name: JsonDefinitionRef(defn)
            for name, defn in self._d.get("component_definitions", {}).items()
        }

    @property
    def component_definitions(self):
        """Iterable of JsonDefinitionRef — used for depth analysis in load()."""
        return [
            JsonDefinitionRef(d)
            for d in self._d.get("component_definitions", {}).values()
        ]

    @property
    def scenes(self):
        # No scene/camera data in the JSON snapshot; live import skips cameras.
        return []

    @property
    def camera(self):
        return JsonCamera(self._d.get("camera"))

    @property
    def layers(self):
        return [JsonLayer(l) for l in self._d.get("layers", [])]
