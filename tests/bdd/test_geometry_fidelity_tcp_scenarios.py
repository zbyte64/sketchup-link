"""
test_geometry_fidelity_tcp_scenarios.py — BDD scenario runner for
geometry_fidelity_tcp.feature.

Auto-discovers all scenarios in tests/bdd/features/geometry_fidelity_tcp.feature
and maps them to the step definitions in conftest.py (TCP-mode steps).

All scenarios use the "Given SketchUp is serving on TCP" background step,
which connects to the Docker Windows VM's TCP port instead of a local
Unix-socket Ruby mock server.
"""
from pytest_bdd import scenario


# ---------------------------------------------------------------------------
# Scenario: Transform matrix round-trip preserves identity (TCP mode)
# ---------------------------------------------------------------------------


@scenario(
    'features/geometry_fidelity_tcp.feature',
    'Transform matrix round-trip preserves identity',
)
def test_transform_matrix_identity_tcp():
    pass


# ---------------------------------------------------------------------------
# Scenario: Face materials are correctly assigned (TCP mode)
# ---------------------------------------------------------------------------


@scenario(
    'features/geometry_fidelity_tcp.feature',
    'Face materials are correctly assigned',
)
def test_face_materials_correct_tcp():
    pass


# ---------------------------------------------------------------------------
# Scenario: All entities are present after import (TCP mode)
# ---------------------------------------------------------------------------


@scenario(
    'features/geometry_fidelity_tcp.feature',
    'All entities are present after import',
)
def test_all_entities_present_tcp():
    pass


# ---------------------------------------------------------------------------
# Scenario: Hidden layer entities are excluded (TCP mode)
# ---------------------------------------------------------------------------


@scenario(
    'features/geometry_fidelity_tcp.feature',
    'Hidden layer entities are excluded',
)
def test_hidden_layer_excluded_tcp():
    pass
