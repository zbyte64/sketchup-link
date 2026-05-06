"""Tests for RemoteControl.row_major_to_transformation (matrix roundtrip)."""

from __future__ import annotations

import json

import pytest

from tests.unit.conftest import run_ruby


@pytest.mark.ruby
class TestRemoteControlMatrix:
    """Tests the inverse transform."""

    INCHES_TO_METERS = 0.0254
    METERS_TO_INCHES = 1.0 / 0.0254

    def _roundtrip(self, col_major: list[float]) -> dict:
        """Serialize to row-major (meters), convert back via row_major_to_transformation, then serialize again."""
        return run_ruby(
            "remote_control_test.rb",
            {"action": "roundtrip", "column_major": col_major},
        )

    def _serialize_and_convert_back(self, row_major_meters: list[float]) -> dict:
        """Pass row-major (meters) through the inverse, then serialize the result."""
        return run_ruby(
            "remote_control_test.rb",
            {"action": "inverse", "row_major": row_major_meters},
        )

    def test_roundtrip_identity(self):
        """Identity: serialize -> deserialize -> serialize yields identity."""
        col_major = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        result = self._roundtrip(col_major)
        rm = result["roundtripped"]
        assert rm == pytest.approx(
            [1, 0, 0, 0.0, 0, 1, 0, 0.0, 0, 0, 1, 0.0, 0, 0, 0, 1]
        )

    def test_roundtrip_translation(self):
        """Translate by (3, 0, 0) meters: roundtrip preserves."""
        col_major = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 3, 0, 0, 1]
        result = self._roundtrip(col_major)
        rm = result["roundtripped"]
        assert rm[3] == pytest.approx(3.0 * self.INCHES_TO_METERS)
        assert rm[7] == pytest.approx(0.0)
        assert rm[11] == pytest.approx(0.0)

    def test_roundtrip_random(self):
        """Random matrices: roundtrip within float epsilon."""
        import random

        for _ in range(20):
            col_major = [random.uniform(-5, 5) for _ in range(16)]
            result = self._roundtrip(col_major)
            rm = result["roundtripped"]
            for row in range(4):
                for col in range(4):
                    expected = col_major[col * 4 + row]
                    if col == 3 and row < 3:
                        expected *= self.INCHES_TO_METERS
                    assert rm[row * 4 + col] == pytest.approx(expected, abs=1e-10)

    def test_translation_inches_to_meters(self):
        """The inverse correctly converts meters back to inches internally."""
        # Start with row-major (meters): translate by (1.0, 2.0, 3.0) meters
        row_major = [1, 0, 0, 1.0, 0, 1, 0, 2.0, 0, 0, 1, 3.0, 0, 0, 0, 1]
        result = self._serialize_and_convert_back(row_major)
        rm = result["result"]
        # After roundtrip, should still be same row-major values
        assert rm[3] == pytest.approx(1.0)
        assert rm[7] == pytest.approx(2.0)
        assert rm[11] == pytest.approx(3.0)
