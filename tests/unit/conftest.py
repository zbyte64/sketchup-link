"""Conftest for unit tests — provides ruby_subprocess fixture for running Ruby helpers."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

RUBY_HELPERS_DIR = Path(__file__).parent / "ruby_test_helpers"
"""Directory containing Ruby test helper scripts."""

RUBY_PLUGIN_SOURCE = Path(__file__).parent.parent.parent
"""Path to Ruby plugin source root (for require_relative / load)."""


def find_ruby() -> str:
    """Return path to ruby executable, or skip if not found."""
    for candidate in ("ruby", "ruby3", "ruby3.2", "ruby3.3"):
        try:
            result = subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return candidate
        except FileNotFoundError:
            continue
    pytest.skip("Ruby executable not found — Ruby-side tests skipped")


@pytest.fixture(scope="session")
def ruby_executable() -> str:
    """Return path to the Ruby executable."""
    return find_ruby()


@pytest.fixture
def ruby_subprocess(request: pytest.FixtureRequest, ruby_executable: str) -> dict:
    """Run a Ruby test helper script and return parsed JSON output.

    The test must set ``request.param`` to the name of the helper script
    (relative to ``ruby_test_helpers/``), and ``request.param_input`` to
    the JSON payload sent via stdin.

    Use the ``run_ruby`` shorthand fixture instead when possible.
    """
    script_name: str = request.param
    input_data: str | bytes | None = getattr(request, "param_input", None)
    script_path = RUBY_HELPERS_DIR / script_name

    if not script_path.exists():
        pytest.fail(f"Ruby helper script not found: {script_path}")

    env = {
        "RUBY_PLUGIN_SOURCE": str(RUBY_PLUGIN_SOURCE),
        "RUBYOPT": "-W0",  # Suppress warnings for stubs
    }

    kwargs: dict = {}
    if input_data is not None:
        kwargs["input"] = json.dumps(input_data) if not isinstance(input_data, bytes) else input_data

    result = subprocess.run(
        [ruby_executable, str(script_path)],
        capture_output=True,
        text=True,
        timeout=30,
        env={**env, **{k: str(v) for k, v in kwargs.pop("env_extra", {}).items()}},
        **kwargs,
    )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        pytest.fail(
            f"Ruby helper {script_name!r} failed (exit={result.returncode}):\n"
            f"  stderr: {stderr}\n"
            f"  stdout: {result.stdout.strip()}"
        )

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        pytest.fail(
            f"Ruby helper {script_name!r} produced invalid JSON:\n"
            f"  error: {e}\n"
            f"  stdout: {result.stdout.strip()}"
        )


def run_ruby(
    script_name: str,
    input_data: object | None = None,
    ruby_executable: str | None = None,
) -> dict:
    """Run a Ruby helper script and return parsed JSON output.

    This is a programmatic counterpart to the ``ruby_subprocess`` fixture.
    Use it when you need to invoke the same helper multiple times with
    different inputs (the fixture is limited to one invocation per test).
    """
    if ruby_executable is None:
        ruby_executable = find_ruby()
    script_path = RUBY_HELPERS_DIR / script_name
    if not script_path.exists():
        pytest.fail(f"Ruby helper script not found: {script_path}")

    env = {
        "RUBY_PLUGIN_SOURCE": str(RUBY_PLUGIN_SOURCE),
        "RUBYOPT": "-W0",
    }

    kwargs: dict = {}
    if input_data is not None:
        kwargs["input"] = json.dumps(input_data)

    result = subprocess.run(
        [ruby_executable, str(script_path)],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        **kwargs,
    )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        pytest.fail(
            f"Ruby helper {script_name!r} failed (exit={result.returncode}):\n"
            f"  stderr: {stderr}\n"
            f"  stdout: {result.stdout.strip()}"
        )

    return json.loads(result.stdout)
