# frozen_string_literal: true

require 'json'

# ------------------------------------------------------------------
# SketchUp API stubs — defined before requiring source files
# ------------------------------------------------------------------

module Sketchup
  class Color < Array
    def initialize(r = 0, g = 0, b = 0, a = 255)
      replace([r, g, b, a])
    end
    def red   = self[0] || 0
    def green = self[1] || 0
    def blue  = self[2] || 0
    def alpha = self[3] || 255
  end

  class Face; end
  class Edge; end
  class Group; end
  class ComponentInstance; end
  class ComponentDefinition; end
end

module Geom
  Point3d  = Struct.new(:x, :y, :z)
  Vector3d = Struct.new(:x, :y, :z) do
    def to_a = [x, y, z]
  end
end

# ------------------------------------------------------------------
# Load serializer source
# ------------------------------------------------------------------

serializer_dir = File.join(ENV.fetch('RUBY_PLUGIN_SOURCE'), 'sketchup_link/serializer')
$LOAD_PATH << serializer_dir
require 'entity_serializer'
require 'transform_serializer'

# ------------------------------------------------------------------
# Stub builders — convert JSON data into mock SketchUp objects
# ------------------------------------------------------------------

module StubBuilders
  # Build a mesh-like object from { points:, uvs:, polygons: }
  def self.build_mesh(data)
    pts   = data['points']   || []
    uvs   = data['uvs']      || []
    polys = data['polygons'] || []

    uvq = Struct.new(:x, :y, :z)

    mesh_obj = Object.new
    mesh_obj.define_singleton_method(:count_points)   { pts.length }
    mesh_obj.define_singleton_method(:point_at)       { |i| Geom::Point3d.new(*pts[i - 1]) }
    mesh_obj.define_singleton_method(:uv_at) do |i, _front_face|
      u, v = uvs[i - 1] || [0.0, 0.0]
      uvq.new(u, v, 1.0)
    end
    mesh_obj.define_singleton_method(:count_polygons) { polys.length }
    mesh_obj.define_singleton_method(:polygon_at)     { |i| polys[i - 1] }
    mesh_obj
  end

  # Build a loop-like object from an array of points
  def self.build_loop(verts_data)
    vertices = verts_data.map do |p|
      v = Object.new
      v.define_singleton_method(:position) { Geom::Point3d.new(p['x'] || p[0], p['y'] || p[1], p['z'] || p[2]) }
      v
    end
    loop_obj = Object.new
    loop_obj.define_singleton_method(:vertices) { vertices }
    loop_obj
  end

  # Build a material-like object
  def self.build_material(data)
    return nil if data.nil?

    mat = Object.new
    mat.define_singleton_method(:name)  { data['name'] || '' }
    mat.define_singleton_method(:color) { StubBuilders.build_color(data['color'] || [128, 128, 128, 255]) }
    mat.define_singleton_method(:alpha) { data['alpha'] || 255 }
    if data['texture']
      tex = Object.new
      tex.define_singleton_method(:filename)     { data['texture']['filename'] || '' }
      tex.define_singleton_method(:width)        { data['texture']['width'] || 1 }
      tex.define_singleton_method(:height)       { data['texture']['height'] || 1 }
      tex.define_singleton_method(:image_width)  { data['texture']['image_width'] || 1 }
      tex.define_singleton_method(:image_height) { data['texture']['image_height'] || 1 }
      tex.define_singleton_method(:write)        { |_path| nil }
      mat.define_singleton_method(:texture) { tex }
    else
      mat.define_singleton_method(:texture) { nil }
    end
    mat
  end

  # Build a layer-like object
  def self.build_layer(data)
    return nil if data.nil? || data.empty?

    layer = Object.new
    layer.define_singleton_method(:name)       { data['name'] || '' }
    layer.define_singleton_method(:visible?)   { data['visible'] != false }
    layer.define_singleton_method(:color)      { StubBuilders.build_color(data['color'] || [200, 200, 200, 255]) }
    layer.define_singleton_method(:line_width) { data['line_width'] || 1 }
    layer
  end

  # Build a Color from [r, g, b, a]
  def self.build_color(arr)
    Sketchup::Color.new(arr[0] || 0, arr[1] || 0, arr[2] || 0, arr[3] || 255)
  end

  # Build a Point3d from { x:, y:, z: } or [x, y, z]
  def self.build_point(data)
    if data.is_a?(Array)
      Geom::Point3d.new(data[0], data[1], data[2])
    else
      Geom::Point3d.new(data['x'], data['y'], data['z'])
    end
  end

  # Build a transformation from a 16-element flat array
  def self.build_transformation(arr)
    t = Object.new
    t.define_singleton_method(:to_a) { arr }
    t
  end

  # Build an entities collection from an array of entity descriptions.
  def self.build_entities(ents_data)
    ents_data.map { |ed| build_entity(ed) }
  end

  # Dispatch to the correct builder based on entity type field.
  def self.build_entity(data)
    type = data['type'] || data['class']
    case type
    when 'Sketchup::Face', 'Face' then build_face(data)
    when 'Sketchup::Edge', 'Edge' then build_edge(data)
    when 'Sketchup::Group', 'Group' then build_group(data)
    when 'Sketchup::ComponentInstance', 'ComponentInstance' then build_instance(data)
    when 'Sketchup::ComponentDefinition', 'ComponentDefinition' then build_definition(data)
    else
      e = Object.new
      e.define_singleton_method(:persistent_id) { data['persistent_id'] || data['entityID'] }
      e.define_singleton_method(:entityID)      { data['entityID'] || data['persistent_id'] }
      e
    end
  end

  def self.build_face(data)
    face = Sketchup::Face.new
    face.define_singleton_method(:mesh)              { |_| StubBuilders.build_mesh(data['mesh'] || {}) }
    face.define_singleton_method(:outer_loop)        { StubBuilders.build_loop(data['outer_loop'] || []) }
    face.define_singleton_method(:loops)             { (data['loops'] || []).map { |l| StubBuilders.build_loop(l) } }
    face.define_singleton_method(:material)          { StubBuilders.build_material(data['material']) }
    face.define_singleton_method(:back_material)     { StubBuilders.build_material(data['back_material']) }
    face.define_singleton_method(:layer)             { StubBuilders.build_layer(data['layer']) }
    face.define_singleton_method(:normal)            { n = data['normal'] || [0, 0, 1]; Geom::Vector3d.new(n[0], n[1], n[2]) }
    face.define_singleton_method(:area)              { data['area'] || 0.0 }
    face.define_singleton_method(:persistent_id)     { data['persistent_id'] }
    face.define_singleton_method(:entityID)          { data['entityID'] || data['persistent_id'] }
    face
  end

  def self.build_edge(data)
    edge = Sketchup::Edge.new
    vertices = (data['vertices'] || []).map { |v|
      v_obj = Object.new
      v_obj.define_singleton_method(:position) { StubBuilders.build_point(v) }
      v_obj
    }
    edge.define_singleton_method(:vertices)          { vertices }
    edge.define_singleton_method(:soft?)             { data['soft'] == true }
    edge.define_singleton_method(:smooth?)           { data['smooth'] == true }
    edge.define_singleton_method(:hidden?)           { data['hidden'] == true }
    edge.define_singleton_method(:layer)             { StubBuilders.build_layer(data['layer']) }
    edge.define_singleton_method(:material)          { StubBuilders.build_material(data['material']) }
    edge.define_singleton_method(:persistent_id)     { data['persistent_id'] }
    edge.define_singleton_method(:entityID)          { data['entityID'] || data['persistent_id'] }
    edge
  end

  def self.build_group(data)
    group = Sketchup::Group.new
    group.define_singleton_method(:name)             { data['name'] || '' }
    group.define_singleton_method(:transformation)   { StubBuilders.build_transformation(data['transformation'] || Array.new(16, 0.0).tap { |a| a[0] = a[5] = a[10] = a[15] = 1.0 }) }
    group.define_singleton_method(:layer)            { StubBuilders.build_layer(data['layer']) }
    group.define_singleton_method(:entities)         { StubBuilders.build_entities(data['entities'] || []) }
    group.define_singleton_method(:persistent_id)    { data['persistent_id'] }
    group.define_singleton_method(:entityID)         { data['entityID'] || data['persistent_id'] }
    group
  end

  def self.build_instance(data)
    inst = Sketchup::ComponentInstance.new
    defn = Sketchup::ComponentDefinition.new
    defn.define_singleton_method(:name) { data['definition_name'] || '' }
    inst.define_singleton_method(:definition)        { defn }
    inst.define_singleton_method(:transformation)    { StubBuilders.build_transformation(data['transformation'] || Array.new(16, 0.0).tap { |a| a[0] = a[5] = a[10] = a[15] = 1.0 }) }
    inst.define_singleton_method(:layer)             { StubBuilders.build_layer(data['layer']) }
    inst.define_singleton_method(:persistent_id)     { data['persistent_id'] }
    inst.define_singleton_method(:entityID)          { data['entityID'] || data['persistent_id'] }
    inst
  end

  def self.build_definition(data)
    defn = Sketchup::ComponentDefinition.new
    defn.define_singleton_method(:name)                { data['name'] || '' }
    defn.define_singleton_method(:guid)                { data['guid'] || '' }
    defn.define_singleton_method(:count_instances)     { data['count_instances'] || 0 }
    defn.define_singleton_method(:count_used_instances) { data['count_used_instances'] || 0 }
    defn.define_singleton_method(:entities)            { StubBuilders.build_entities(data['entities'] || []) }
    defn.define_singleton_method(:persistent_id)       { data['persistent_id'] }
    defn.define_singleton_method(:entityID)            { data['entityID'] || data['persistent_id'] }
    defn
  end
end

# ------------------------------------------------------------------
# Main dispatch
# ------------------------------------------------------------------

input  = JSON.parse(STDIN.read)
action = input['action']
entity = input['entity']

result = case action
         when 'serialize_face'
           SketchupLink::Serializer::EntitySerializer.serialize_face(StubBuilders.build_face(entity))
         when 'serialize_edge'
           SketchupLink::Serializer::EntitySerializer.serialize_edge(StubBuilders.build_edge(entity))
         when 'serialize_group'
           SketchupLink::Serializer::EntitySerializer.serialize_group(StubBuilders.build_group(entity))
         when 'serialize_instance'
           SketchupLink::Serializer::EntitySerializer.serialize_instance(StubBuilders.build_instance(entity))
         when 'serialize_definition'
           SketchupLink::Serializer::EntitySerializer.serialize_definition(StubBuilders.build_definition(entity))
         when 'serialize_material'
           no_textures = input['no_textures'] == true
           binary_textures = input['binary_textures'] == true
           SketchupLink::Serializer::EntitySerializer.serialize_material(
             StubBuilders.build_material(entity),
             no_textures: no_textures,
             binary_textures: binary_textures
           )
         when 'serialize_layer'
           SketchupLink::Serializer::EntitySerializer.serialize_layer(StubBuilders.build_layer(entity))
         when 'serialize_entities'
           SketchupLink::Serializer::EntitySerializer.serialize_entities(StubBuilders.build_entities(entity['entities'] || []))
         when 'persistent_id'
           SketchupLink::Serializer::EntitySerializer.persistent_id(StubBuilders.build_entity(entity))
         when 'color_to_hash'
           SketchupLink::Serializer::EntitySerializer.color_to_hash(StubBuilders.build_color(entity))
         when 'point_to_meters'
           SketchupLink::Serializer::EntitySerializer.point_to_meters(StubBuilders.build_point(entity))
         when 'serialize'
           SketchupLink::Serializer::EntitySerializer.serialize(StubBuilders.build_entity(entity))
         else
           { 'error' => "Unknown action: #{action}" }
         end

puts JSON.generate(result)
