"""Tests for TransformSerializer.serialize via Ruby subprocess."""

from __future__ import annotations

import json
import math
import random

import pytest

from tests.unit.conftest import run_ruby


@pytest.mark.ruby
class TestTransformSerializer:
    """TransformSerializer correctness tests."""

    INCHES_TO_METERS = 0.0254

    def _serialize(self, col_major: list[float]) -> dict:
        """Run Ruby helper and return result dict."""
        return run_ruby("transform_serializer_test.rb", {"column_major": col_major})

    def _row_major(self, result: dict) -> list[float]:
        """Extract row_major array from result."""
        return result["row_major"]

    def test_identity_transform(self):
        """Identity matrix: translation zeros remain zero."""
        col_major = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        rm = self._row_major(self._serialize(col_major))
        # Transpose of identity is identity
        assert rm == pytest.approx([1, 0, 0, 0.0, 0, 1, 0, 0.0, 0, 0, 1, 0.0, 0, 0, 0, 1])

    def test_translation_only(self):
        """Pure translation: 1,2,3 inches -> 0.0254, 0.0508, 0.0762 meters."""
        # In column-major, translation is at indices 12, 13, 14
        col_major = [1, 0, 0, 0,  0, 1, 0, 0,  0, 0, 1, 0,  1.0, 2.0, 3.0, 1]
        rm = self._row_major(self._serialize(col_major))
        # In row-major, translation is at indices 3, 7, 11
        assert rm[3] == pytest.approx(self.INCHES_TO_METERS)
        assert rm[7] == pytest.approx(2.0 * self.INCHES_TO_METERS)
        assert rm[11] == pytest.approx(3.0 * self.INCHES_TO_METERS)

    def test_rotation_preserved(self):
        """Rotation components unchanged, only translation scaled."""
        # Rotation of 90 degrees around Z (column-major):
        # [0, 1, 0, 0,  -1, 0, 0, 0,  0, 0, 1, 0,  0, 0, 0, 1]
        col_major = [0, 1, 0, 0,  -1, 0, 0, 0,  0, 0, 1, 0,  0, 0, 0, 1]
        rm = self._row_major(self._serialize(col_major))
        # Rotation in row-major should be the transpose of column-major
        # Column-major was:  m0=0 (col0,row0), m1=1 (col0,row1), m4=-1 (col1,row0), m5=0 (col1,row1)
        # Row-major becomes: m0=0 (row0,col0), m1=-1 (row0,col1), m4=1 (row1,col0), m5=0 (row1,col1)
        assert rm[0] == pytest.approx(0.0)
        assert rm[1] == pytest.approx(-1.0)
        assert rm[4] == pytest.approx(1.0)
        assert rm[5] == pytest.approx(0.0)

    def test_scale_preserved(self):
        """Non-uniform scale preserved, translation scaled."""
        col_major = [2, 0, 0, 0,  0, 3, 0, 0,  0, 0, 4, 0,  5.0, 6.0, 7.0, 1]
        rm = self._row_major(self._serialize(col_major))
        # Transposed: m0=2, m5=3, m10=4 -> rm[0]=2, rm[5]=3, rm[10]=4
        assert rm[0] == pytest.approx(2.0)
        assert rm[5] == pytest.approx(3.0)
        assert rm[10] == pytest.approx(4.0)
        # Translation (indices 3, 7, 11) scaled
        assert rm[3] == pytest.approx(5.0 * self.INCHES_TO_METERS)
        assert rm[7] == pytest.approx(6.0 * self.INCHES_TO_METERS)
        assert rm[11] == pytest.approx(7.0 * self.INCHES_TO_METERS)

    def test_full_affine(self):
        """Combined rotation+translation+scale."""
        col_major = [2, 0, 0, 0,  0, 1, 0, 0,  0, 0, 1, 0,  10.0, 20.0, 30.0, 1]
        rm = self._row_major(self._serialize(col_major))
        # X-scale=2 -> rm[0]=2
        assert rm[0] == pytest.approx(2.0)
        # Translation
        assert rm[3] == pytest.approx(10.0 * self.INCHES_TO_METERS)
        assert rm[7] == pytest.approx(20.0 * self.INCHES_TO_METERS)
        assert rm[11] == pytest.approx(30.0 * self.INCHES_TO_METERS)

    def test_random_matrices(self):
        """Property: transposing twice recovers original (except translation scaling)."""
        for _ in range(20):
            col_major = [random.uniform(-10, 10) for _ in range(16)]
            rm = self._row_major(self._serialize(col_major))
            # Verify transpose: rm[i*4+j] should be cm[j*4+i] (with translation scaled)
            for row in range(4):
                for col in range(4):
                    expected = col_major[col * 4 + row]
                    if col == 3 and row < 3:  # translation column in row-major, skip homogeneous [3,3]
                        expected *= self.INCHES_TO_METERS
                    assert rm[row * 4 + col] == pytest.approx(expected)
