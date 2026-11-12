"""A missing Ruby must fail the unit suite by default, never skip silently.

The Ruby-backed tests cover most of the plugin. If they were skipped without a trace, a host
without Ruby would report a green run that exercised none of the Ruby code.
"""

import pytest

from tests.unit import conftest as unit_conftest


def test_missing_ruby_fails_by_default(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.delenv("SKETCHUP_LINK_SKIP_RUBY", raising=False)
    with pytest.raises(pytest.fail.Exception, match="Ruby executable not found"):
        unit_conftest.find_ruby()


def test_explicit_opt_out_skips_visibly(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.setenv("SKETCHUP_LINK_SKIP_RUBY", "1")
    with pytest.raises(pytest.skip.Exception):
        unit_conftest.find_ruby()
