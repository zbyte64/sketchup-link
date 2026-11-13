"""reshape_face adds the new face to the owner of the old one, for loose top-level and grouped faces alike."""

from __future__ import annotations

import pytest

from tests.unit.conftest import run_ruby


@pytest.mark.ruby
class TestReshapeOwner:
    def test_loose_top_level_face_is_rebuilt_in_the_model_entities(self):
        r = run_ruby("remote_control_reshape_test.rb", {"persistent_id": 1})
        assert r["status"] == 200, r
        assert r["added_to"] == ["top"]
        assert r["erased"] == [1]

    def test_grouped_face_is_rebuilt_in_its_definition_entities(self):
        r = run_ruby("remote_control_reshape_test.rb", {"persistent_id": 2})
        assert r["status"] == 200, r
        assert r["added_to"] == ["group"]
        assert r["erased"] == [2]
