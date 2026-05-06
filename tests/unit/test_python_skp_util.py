"""Pure Python unit tests for blender_plugin/skp_util.py."""
from __future__ import annotations


from blender_plugin.skp_util import (
    SKP_util,
    EntityType,
    group_name,
    group_safe_name,
    inherent_default_mat,
    keep_offset,
    proxy_dict,
)
import deal
test_group_name = deal.cases(group_name)
test_group_safe_name = deal.cases(group_safe_name)


class TestProxyDict:
    def test_proxy_suffix_stripped(self):
        d = proxy_dict({"foo": "bar"})
        assert d["foo_proxy"] == "bar"

    def test_proxy_key_not_found_returns_proxy_key(self):
        d = proxy_dict({"foo_proxy": "bar"})
        assert d["foo_proxy"] == "bar"

    def test_direct_key_access(self):
        d = proxy_dict({"foo": "bar"})
        assert d["foo"] == "bar"

    def test_keyerror_prints_and_returns_none(self, capsys):
        d = proxy_dict({"foo": "bar"})
        result = d["nonexistent"]
        assert result is None
        captured = capsys.readouterr()
        assert "KeyError: nonexistent" in captured.out


class TestKeepOffset:
    def test_first_access_returns_0(self):
        o = keep_offset()
        assert o["a"] == 0

    def test_same_key_returns_same_offset(self):
        o = keep_offset()
        o["a"]
        assert o["a"] == 0

    def test_sequential_assignment(self):
        o = keep_offset()
        assert o["a"] == 0
        assert o["b"] == 1
        assert o["c"] == 2



class TestInherentDefaultMat:
    def test_mat_with_name_returns_name(self):
        mat = type("Mat", (), {"name": "Red"})()
        assert inherent_default_mat(mat, "DefaultMaterial") == "Red"

    def test_none_mat_returns_default(self):
        assert inherent_default_mat(None, "CustomDefault") == "CustomDefault"

    def test_mat_name_default_and_custom_default(self):
        mat = type("Mat", (), {"name": "DefaultMaterial"})()
        assert inherent_default_mat(mat, "CustomDefault") == "DefaultMaterial"


class MockEntities:
    """Minimal mock for entity container with .groups and .instances lists."""


class MockEntity:
    """Minimal mock for a single entity (group or instance)."""


def _empty_entities():
    e = MockEntities()
    e.groups = []
    e.instances = []
    return e


def _make_group(layer=None, entities=None):
    g = MockEntity()
    g.layer = layer
    g.entities = entities if entities is not None else _empty_entities()
    return g


def _make_instance(layer=None, def_entities=None):
    inst = MockEntity()
    inst.layer = layer
    inst.definition = MockEntities()
    inst.definition.entities = def_entities if def_entities is not None else _empty_entities()
    return inst


class TestComponentDeps:
    def test_empty_entities_returns_0(self):
        """Empty entities with comp=False returns own_depth of 0."""
        util = SKP_util()
        assert util.component_deps(_empty_entities(), comp=False) == 0

    def test_single_group_no_nesting_returns_1(self):
        util = SKP_util()
        top = MockEntities()
        top.groups = [_make_group()]
        top.instances = []
        assert util.component_deps(top) == 1

    def test_nested_group_returns_1(self):
        """Groups always recurse with comp=False so nested groups do not add depth."""
        util = SKP_util()
        inner = _make_group()
        inner_entities = MockEntities()
        inner_entities.groups = [inner]
        inner_entities.instances = []
        outer = _make_group(entities=inner_entities)
        top = MockEntities()
        top.groups = [outer]
        top.instances = []
        assert util.component_deps(top) == 1

    def test_single_instance_returns_2(self):
        util = SKP_util()
        top = MockEntities()
        top.groups = []
        top.instances = [_make_instance()]
        assert util.component_deps(top) == 2

    def test_instance_with_nested_instance_returns_3(self):
        util = SKP_util()
        inner = _make_instance()
        outer = _make_instance(def_entities=_make_entities_with_instances([inner]))
        top = MockEntities()
        top.groups = []
        top.instances = [outer]
        assert util.component_deps(top) == 3

    def test_layers_skip_excludes_group(self):
        SKP_util.layers_skip = ["skip_layer"]
        util = SKP_util()
        top = MockEntities()
        top.groups = [_make_group(layer="skip_layer")]
        top.instances = []
        assert util.component_deps(top) == 1

    def test_layers_skip_excludes_instance(self):
        SKP_util.layers_skip = ["skip_layer"]
        util = SKP_util()
        top = MockEntities()
        top.groups = []
        top.instances = [_make_instance(layer="skip_layer")]
        assert util.component_deps(top) == 1

    def test_mixed_groups_and_instances_max_wins(self):
        util = SKP_util()
        top = MockEntities()
        top.groups = [_make_group()]  # depth 1
        top.instances = [_make_instance()]  # depth 2
        assert util.component_deps(top) == 2

    def test_comp_false_reduces_own_depth(self):
        util = SKP_util()
        assert util.component_deps(_empty_entities(), comp=False) == 0


def _make_entities_with_instances(instances):
    e = MockEntities()
    e.groups = []
    e.instances = instances
    return e
