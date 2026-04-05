# frozen_string_literal: true
# tests/integration/factories.rb
#
# Fuzzy data factories for integration tests.
# No SketchUp APIs — pure Ruby stdlib only (securerandom).
#
# All values are randomized except fields that test_live_adapter.py asserts
# on directly (material names, exact RGB channels, layer names, group name,
# num_instances, etc.). The rand_quad_mesh helper guarantees len(verts) ==
# len(uvs) by construction — the critical tessfaces invariant.

require 'securerandom'

module Factories
  # ---------------------------------------------------------------------------
  # Randomization helpers
  # ---------------------------------------------------------------------------

  def self.rand_float(min = -5.0, max = 5.0)
    (min + rand * (max - min)).round(6)
  end

  def self.rand_vertex
    [rand_float, rand_float, rand_float]
  end

  # A planar quad (4 verts) tessellated into 2 triangles.
  # Both verts and uvs use 4.times.map — equal length by construction.
  def self.rand_quad_mesh
    verts = 4.times.map { rand_vertex }
    tris  = [[0, 1, 2], [0, 2, 3]]
    uvs   = 4.times.map { [rand_float(0.0, 1.0), rand_float(0.0, 1.0)] }
    [verts, tris, uvs]
  end

  def self.rand_normal
    [rand_float(-1.0, 1.0), rand_float(-1.0, 1.0), rand_float(-1.0, 1.0)]
  end

  def self.rand_id
    rand(1..99_999)
  end

  def self.rand_color
    { 'r' => rand(0..255), 'g' => rand(0..255), 'b' => rand(0..255), 'a' => 255 }
  end

  def self.identity_transform
    [1, 0, 0, 0,
     0, 1, 0, 0,
     0, 0, 1, 0,
     0, 0, 0, 1]
  end

  # ---------------------------------------------------------------------------
  # Entity factories
  # ---------------------------------------------------------------------------

  def self.face(material: nil, back_material: nil, layer: 'Layer0')
    verts, tris, uvs = rand_quad_mesh
    {
      'type'          => 'Face',
      'persistent_id' => rand_id,
      'normal'        => rand_normal,
      'area'          => rand_float(0.01, 20.0).abs,
      'vertices'      => verts,
      'triangles'     => tris,
      'uvs'           => uvs,
      'outer_loop'    => verts,
      'loops'         => [verts],
      'material'      => material,
      'back_material' => back_material,
      'layer'         => layer
    }
  end

  def self.edge(layer: 'Layer0')
    {
      'type'          => 'Edge',
      'persistent_id' => rand_id,
      'vertices'      => [rand_vertex, rand_vertex],
      'soft'          => [true, false].sample,
      'smooth'        => [true, false].sample,
      'hidden'        => false,
      'layer'         => layer,
      'material'      => nil
    }
  end

  def self.group(name:, layer: 'Furniture', entities: [])
    {
      'type'           => 'Group',
      'persistent_id'  => rand_id,
      'name'           => name,
      'layer'          => layer,
      'transformation' => identity_transform,
      'entities'       => entities
    }
  end

  def self.instance(definition_name:, layer: 'Furniture')
    {
      'type'            => 'ComponentInstance',
      'persistent_id'   => rand_id,
      'definition_name' => definition_name,
      'transformation'  => identity_transform,
      'layer'           => layer
    }
  end

  # ---------------------------------------------------------------------------
  # Material / Layer factories
  # ---------------------------------------------------------------------------

  # r/g/b are pinned so tests can assert exact channel values.
  def self.material(name:, r:, g:, b:, opacity: 1.0)
    {
      'name'    => name,
      'color'   => { 'r' => r, 'g' => g, 'b' => b, 'a' => 255 },
      'opacity' => opacity
    }
  end

  def self.layer(name:, visible:)
    {
      'name'       => name,
      'visible'    => visible,
      'color'      => rand_color,
      'line_width' => rand(1..3)
    }
  end

  # ---------------------------------------------------------------------------
  # Component definition factory
  # ---------------------------------------------------------------------------

  def self.component_definition(name:, num_instances:, num_used_instances:, entities: [])
    {
      'name'               => name,
      'guid'               => SecureRandom.uuid,
      'num_instances'      => num_instances,
      'num_used_instances' => num_used_instances,
      'entities'           => entities
    }
  end

  # ---------------------------------------------------------------------------
  # Canonical test model
  #
  # Exact spec (all tests depend on this shape):
  #   Top-level entities (5):
  #     [0] face  — material='Red', no back_material
  #     [1] face  — back_material='Blue', no material
  #     [2] edge  — no material
  #     [3] group — name='FurnitureGroup', layer='Furniture', identity transform
  #                 entities: [face, edge]
  #     [4] instance — definition_name='Chair', layer='Furniture'
  #   Materials (2): Red(220,20,20) and Blue(20,20,200)
  #   Layers (3): Layer0(visible), Furniture(visible), Hidden(invisible)
  #   component_definitions (1): 'Chair' with 2 faces, num_instances=1
  # ---------------------------------------------------------------------------

  def self.test_model
    red_mat  = material(name: 'Red',  r: 220, g: 20,  b: 20)
    blue_mat = material(name: 'Blue', r: 20,  g: 20,  b: 200)

    layer0        = layer(name: 'Layer0',    visible: true)
    furniture_lay = layer(name: 'Furniture', visible: true)
    hidden_lay    = layer(name: 'Hidden',    visible: false)

    chair_def = component_definition(
      name: 'Chair',
      num_instances: 1,
      num_used_instances: 1,
      entities: [face(layer: 'Layer0'), face(layer: 'Layer0')]
    )

    furniture_group = group(
      name: 'FurnitureGroup',
      layer: 'Furniture',
      entities: [face(layer: 'Furniture'), edge(layer: 'Furniture')]
    )

    {
      'model_guid'            => SecureRandom.uuid,
      'title'                 => 'Integration Test Model',
      'path'                  => '/tmp/test.skp',
      'entities'              => [
        face(material: 'Red',   layer: 'Layer0'),
        face(back_material: 'Blue', layer: 'Layer0'),
        edge(layer: 'Layer0'),
        furniture_group,
        instance(definition_name: 'Chair', layer: 'Furniture')
      ],
      'materials'             => [red_mat, blue_mat],
      'layers'                => [layer0, furniture_lay, hidden_lay],
      'component_definitions' => { 'Chair' => chair_def }
    }
  end
end
