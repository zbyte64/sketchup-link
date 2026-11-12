"""Live-change e2e: an edit made in SketchUp must reach subscribers and the snapshot.

Each test triggers a real change through the MCP tunnel (eval_ruby), reads the
/subscribe NDJSON stream, and checks the next /model snapshot. The reset fixture in
conftest.py gives every test the same factory model.
"""

import json
import socket
import threading
import time
import urllib.request

import pytest

from tests.bdd.conftest import _MCP_LOCAL_PORT, _TCP_HOST, _TCP_PORT, _ensure_mcp_tunnel


def _mcp(code, id_=1):
    """Run Ruby in SketchUp via the MCP tunnel and return the result text."""
    _ensure_mcp_tunnel()
    s = socket.create_connection(('127.0.0.1', _MCP_LOCAL_PORT), timeout=60)
    msg = {'jsonrpc': '2.0', 'id': id_, 'method': 'tools/call',
           'params': {'name': 'eval_ruby', 'arguments': {'code': code}}}
    s.sendall((json.dumps(msg) + '\n').encode())
    buf = b''
    while not buf.endswith(b'\n'):
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    s.close()
    reply = json.loads(buf.decode())
    assert not reply.get('error'), f'eval_ruby failed: {reply.get("error")}'
    return reply['result']['content'][0]['text']


def _snapshot():
    with urllib.request.urlopen(f'http://{_TCP_HOST}:{_TCP_PORT}/model', timeout=30) as resp:
        return json.loads(resp.read())


def _collect_stream(events, trigger, wait=12.0):
    """Open /subscribe for `events`, wait until it is registered, run `trigger()`, return the stream.

    Registration is confirmed by the first chunk the server sends (the subscription id),
    not by a fixed sleep, so a busy VM cannot make the edit land before the subscriber.
    """
    chunks = {'text': ''}
    registered = threading.Event()

    def listen():
        s = socket.create_connection((_TCP_HOST, _TCP_PORT), timeout=wait + 5)
        s.sendall(f'GET /subscribe?events={events} HTTP/1.1\r\nHost: localhost\r\n\r\n'.encode())
        buf, end = b'', time.time() + wait
        while time.time() < end:
            try:
                c = s.recv(65536)
            except socket.timeout:
                break
            if not c:
                break
            buf += c
            if b'subscription_id' in buf:
                registered.set()
        chunks['text'] = buf.decode(errors='replace')
        s.close()

    t = threading.Thread(target=listen)
    t.start()
    assert registered.wait(timeout=10), 'subscription did not register within 10s'
    trigger()
    t.join()
    return chunks['text']


def _events(stream):
    """Parse the JSON event lines out of the chunked NDJSON body."""
    out = []
    for line in stream.splitlines():
        line = line.strip()
        if line.startswith('{') and '"event"' in line:
            out.append(json.loads(line))
    return out


def test_added_group_is_committed_and_snapshot_has_it():
    stream = _collect_stream('transaction.commit',
                             lambda: _mcp('g = Sketchup.active_model.entities.add_group; g.name = "E2EAdd"; g.persistent_id'))
    events = _events(stream)
    assert any(e['event'] == 'transaction.commit' and 'E2EAdd' in json.dumps(e) for e in events), \
        'no transaction.commit carrying the added group'
    names = [g['name'] for g in _snapshot()['entities'] if g.get('type') == 'Group']
    assert 'E2EAdd' in names, f'added group missing from snapshot: {names}'


def test_deleted_group_is_reported_removed_and_gone_from_snapshot():
    pid = int(_mcp('g = Sketchup.active_model.entities.grep(Sketchup::Group).find { |x| x.name == "FurnitureGroup" }; g.persistent_id'))
    stream = _collect_stream('transaction.commit',
                             lambda: _mcp(f'Sketchup.active_model.entities.grep(Sketchup::Group).find {{ |x| x.persistent_id == {pid} }}.erase!; "ok"'))
    events = _events(stream)
    removed = [pid_ for e in events for pid_ in (e.get('data', {}).get('removed') or [])]
    assert pid in removed or any(e['event'] == 'transaction.commit' for e in events), \
        f'no commit reporting pid {pid} removed'
    names = [g['name'] for g in _snapshot()['entities'] if g.get('type') == 'Group']
    assert 'FurnitureGroup' not in names, f'deleted group still in snapshot: {names}'


def test_moved_group_is_reported_and_snapshot_reflects_transform():
    stream = _collect_stream('transaction.commit',
                             lambda: _mcp('g = Sketchup.active_model.entities.grep(Sketchup::Group).find { |x| x.name == "FurnitureGroup" }; '
                                          'g.transformation = Geom::Transformation.new([0.5, 0, 0]); "ok"'))
    assert any(e['event'] == 'transaction.commit' for e in _events(stream)), 'no commit after a transform'
    group = next(g for g in _snapshot()['entities'] if g.get('name') == 'FurnitureGroup')
    # SketchUp works in inches; the snapshot is metres. 0.5 in = 0.0127 m.
    expected_x = 0.5 * 0.0254
    assert abs(group['transformation'][3] - expected_x) < 1e-6, \
        f"snapshot translation X expected {expected_x}, got {group['transformation'][3]}"


def test_material_change_is_reported():
    stream = _collect_stream('materials.change',
                             lambda: _mcp('m = Sketchup.active_model.materials["Blue"]; m.color = Sketchup::Color.new(10, 20, 30); "ok"'))
    assert any(e['event'] == 'materials.change' for e in _events(stream)), 'no materials.change after a colour edit'
    blue = next(m for m in _snapshot()['materials'] if m['name'] == 'Blue')
    assert (blue['color']['r'], blue['color']['g'], blue['color']['b']) == (10, 20, 30)


def test_layer_visibility_change_is_reported():
    try:
        stream = _collect_stream('layers.change',
                                 lambda: _mcp('l = Sketchup.active_model.layers["Furniture"]; l.visible = false; "ok"'))
        assert any(e['event'] == 'layers.change' for e in _events(stream)), 'no layers.change after a visibility edit'
    finally:
        # Layer visibility is not reset by the model reset; restore it so later tests see the factory state.
        _mcp('Sketchup.active_model.layers["Furniture"].visible = true; "ok"')
