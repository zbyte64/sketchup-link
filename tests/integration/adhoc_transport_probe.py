"""
Ad-hoc transport probe. Runs INSIDE the Blender image (Blender's python, no bpy needed).

Usage (from repo root):
    docker run --rm --network host -v $PWD:/plugin -w /plugin sketchup-link-blender:5.2 \
        sh -c 'B=$(ls -d /opt/blender-*/5.2/python/bin/python3.* | head -1); "$B" tests/integration/adhoc_transport_probe.py'
"""

import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)

logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s %(message)s")

import importlib.util  # noqa: E402

# Load live_adapter without importing the package __init__ (which imports bpy).
spec = importlib.util.spec_from_file_location(
    "blender_plugin.live_adapter",
    os.path.join(REPO, "blender_plugin", "live_adapter.py"),
    submodule_search_locations=None,
)
pkg_spec = importlib.util.spec_from_loader("blender_plugin", loader=None, is_package=True)
pkg = importlib.util.module_from_spec(pkg_spec)
pkg.__path__ = [os.path.join(REPO, "blender_plugin")]
sys.modules["blender_plugin"] = pkg
la = importlib.util.module_from_spec(spec)
sys.modules["blender_plugin.live_adapter"] = la
spec.loader.exec_module(la)

BAD_SOCK = "/tmp/does-not-exist-sketchup-link.sock"
cfg = {
    "mode": "UNIX",
    "socket_path": BAD_SOCK,
    "host": os.environ.get("SKETCHUP_LINK_HOST", "127.0.0.1"),
    "port": int(os.environ.get("SKETCHUP_LINK_PORT", "9876")),
    "binary_textures": False,
}

print("socket exists:", os.path.exists(BAD_SOCK))
try:
    data = la.fetch_model_json(cfg)
    print("TRANSPORT RESULT: ok, keys=%d, model_guid=%s" % (len(data), data.get("model_guid")))
except Exception as exc:  # noqa: BLE001
    print("TRANSPORT RESULT: FAILED: %r" % (exc,))
    sys.exit(1)
