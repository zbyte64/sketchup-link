"""
test_error_handling_scenarios.py — BDD scenario runner for error_handling.feature.

Auto-discovers all scenarios in tests/bdd/features/error_handling.feature and
maps them to the step definitions in conftest.py.
"""
from pytest_bdd import scenario


# ---------------------------------------------------------------------------
# Scenario: Connection fails when SketchUp plugin is not running
# ---------------------------------------------------------------------------


@scenario(
    'features/error_handling.feature',
    'Connection fails when SketchUp plugin is not running',
)
def test_connection_fails():
    pass


# ---------------------------------------------------------------------------
# Scenario: Server returns an HTTP error response
# ---------------------------------------------------------------------------


@scenario(
    'features/error_handling.feature',
    'Server returns an HTTP error response',
)
def test_server_http_error():
    pass


# ---------------------------------------------------------------------------
# Scenario: Model JSON is missing required top-level keys
# ---------------------------------------------------------------------------


@scenario(
    'features/error_handling.feature',
    'Model JSON is missing required top-level keys',
)
def test_missing_top_level_keys():
    pass


# ---------------------------------------------------------------------------
# Scenario: Model contains zero entities
# ---------------------------------------------------------------------------


@scenario(
    'features/error_handling.feature',
    'Model contains zero entities',
)
def test_empty_model():
    pass
