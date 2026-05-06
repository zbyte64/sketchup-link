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
# Load serializer sources
# ------------------------------------------------------------------

serializer_dir = File.join(ENV.fetch('RUBY_PLUGIN_SOURCE'), 'sketchup_link/serializer')
$LOAD_PATH << serializer_dir
require 'entity_serializer'
require 'transform_serializer'
require 'model_serializer'

# ------------------------------------------------------------------
# Stub builders — convert JSON data into mock SketchUp objects
# ------------------------------------------------------------------

module Builders
  def self.color(arr) = Sketchup::Color.new(arr[0] || 0, arr[1] || 0, arr[2] || 0, arr[3] || 255)

  def self.pt(data)
    data.is_a?(Array) ? Geom::Point3d.new(*data) : Geom::Point3d.new(data['x'], data['y'], data['z'])
  end

  def self.trans(arr)
    t = Object.new; t.define_singleton_method(:to_a) { arr }; t
  end

  def self.build_mesh(data)
    pts = data['points'] || []; uvs = data['uvs'] || []; polys = data['polygons'] || []
    uvq = Struct.new(:x, :y, :z)
    m = Object.new
    m.define_singleton_method(:count_points)   { pts.length }
    m.define_singleton_method(:point_at)       { |i| Geom::Point3d.new(*pts[i - 1]) }
    m.define_singleton_method(:uv_at)          { |i, _| u, v = uvs[i - 1] || [0.0, 0.0]; uvq.new(u, v, 1.0) }
    m.define_singleton_method(:count_polygons) { polys.length }
    m.define_singleton_method(:polygon_at)     { |i| polys[i - 1] }
    m
  end

  def self.build_loop(verts)
    vs = verts.map { |p| o = Object.new; o.define_singleton_method(:position) { Builders.pt(p) }; o }
    l = Object.new; l.define_singleton_method(:vertices) { vs }; l
  end

  def self.material(data)
    return nil if data.nil?
    m = Object.new
    m.define_singleton_method(:name)    { data['name'] || '' }
    m.define_singleton_method(:color)   { Builders.color(data['color'] || [128, 128, 128, 255]) }
    m.define_singleton_method(:alpha)   { data['alpha'] || 255 }
    m.define_singleton_method(:texture) { nil }
    m
  end

  def self.layer(data)
    return nil if data.nil? || data.empty?
    l = Object.new
    l.define_singleton_method(:name)       { data['name'] || '' }
    l.define_singleton_method(:visible?)   { data['visible'] != false }
    l.define_singleton_method(:color)      { Builders.color(data['color'] || [200, 200, 200, 255]) }
    l.define_singleton_method(:line_width) { data['line_width'] || 1 }
    l
  end

  def self.face(data)
    f = Sketchup::Face.new
    f.define_singleton_method(:mesh)          { |_| Builders.build_mesh(data['mesh'] || {}) }
    f.define_singleton_method(:outer_loop)    { Builders.build_loop(data['outer_loop'] || []) }
    f.define_singleton_method(:loops)         { (data['loops'] || []).map { |l| Builders.build_loop(l) } }
    f.define_singleton_method(:material)      { Builders.material(data['material']) }
    f.define_singleton_method(:back_material) { Builders.material(data['back_material']) }
    f.define_singleton_method(:layer)         { Builders.layer(data['layer']) }
    f.define_singleton_method(:normal)        { n = data['normal'] || [0, 0, 1]; Geom::Vector3d.new(*n) }
    f.define_singleton_method(:area)          { data['area'] || 0.0 }
    f.define_singleton_method(:persistent_id) { data['persistent_id'] }
    f.define_singleton_method(:entityID)      { data['entityID'] || data['persistent_id'] }
    f
  end

  def self.edge(data)
    e = Sketchup::Edge.new
    vs = (data['vertices'] || []).map { |v| o = Object.new; o.define_singleton_method(:position) { Builders.pt(v) }; o }
    e.define_singleton_method(:vertices)      { vs }
    e.define_singleton_method(:soft?)         { data['soft'] == true }
    e.define_singleton_method(:smooth?)       { data['smooth'] == true }
    e.define_singleton_method(:hidden?)       { data['hidden'] == true }
    e.define_singleton_method(:layer)         { Builders.layer(data['layer']) }
    e.define_singleton_method(:material)      { Builders.material(data['material']) }
    e.define_singleton_method(:persistent_id) { data['persistent_id'] }
    e.define_singleton_method(:entityID)      { data['entityID'] || data['persistent_id'] }
    e
  end

  def self.group(data)
    g = Sketchup::Group.new
    id = Array.new(16, 0.0).tap { |a| a[0] = a[5] = a[10] = a[15] = 1.0 }
    g.define_singleton_method(:name)           { data['name'] || '' }
    g.define_singleton_method(:transformation) { Builders.trans(data['transformation'] || id) }
    g.define_singleton_method(:layer)          { Builders.layer(data['layer']) }
    g.define_singleton_method(:entities)       { Builders.entities(data['entities'] || []) }
    g.define_singleton_method(:persistent_id)  { data['persistent_id'] }
    g.define_singleton_method(:entityID)       { data['entityID'] || data['persistent_id'] }
    g
  end

  def self.instance(data)
    i = Sketchup::ComponentInstance.new
    d = Sketchup::ComponentDefinition.new
    d.define_singleton_method(:name) { data['definition_name'] || '' }
    id = Array.new(16, 0.0).tap { |a| a[0] = a[5] = a[10] = a[15] = 1.0 }
    i.define_singleton_method(:definition)     { d }
    i.define_singleton_method(:transformation) { Builders.trans(data['transformation'] || id) }
    i.define_singleton_method(:layer)          { Builders.layer(data['layer']) }
    i.define_singleton_method(:persistent_id)  { data['persistent_id'] }
    i.define_singleton_method(:entityID)       { data['entityID'] || data['persistent_id'] }
    i
  end

  def self.definition(data)
    d = Sketchup::ComponentDefinition.new
    d.define_singleton_method(:name)                { data['name'] || '' }
    d.define_singleton_method(:guid)                { data['guid'] || '' }
    d.define_singleton_method(:count_instances)     { data['count_instances'] || 0 }
    d.define_singleton_method(:count_used_instances) { data['count_used_instances'] || 0 }
    d.define_singleton_method(:entities)            { Builders.entities(data['entities'] || []) }
    d.define_singleton_method(:persistent_id)       { data['persistent_id'] }
    d.define_singleton_method(:entityID)            { data['entityID'] || data['persistent_id'] }
    d.define_singleton_method(:group?)              { data['group'] == true }
    d
  end

  def self.entity(data)
    case data['type']
    when 'Face' then face(data)
    when 'Edge' then edge(data)
    when 'Group' then group(data)
    when 'ComponentInstance' then instance(data)
    when 'ComponentDefinition' then definition(data)
    else
      o = Object.new
      o.define_singleton_method(:persistent_id) { data['persistent_id'] || data['entityID'] }
      o.define_singleton_method(:entityID)      { data['entityID'] || data['persistent_id'] }
      o
    end
  end

  def self.entities(ents) = ents.map { |e| entity(e) }

  def self.camera(data)
    c = Object.new
    c.define_singleton_method(:eye)          { Builders.pt(data['eye'] || [0, 0, 0]) }
    c.define_singleton_method(:target)       { Builders.pt(data['target'] || [0, 0, -1]) }
    c.define_singleton_method(:up)           { Geom::Vector3d.new(*(data['up'] || [0, 1, 0])) }
    c.define_singleton_method(:perspective?) { data['perspective'] == true }
    c.define_singleton_method(:fov)          { data['fov'] || 45.0 }
    c.define_singleton_method(:aspect_ratio) { data['aspect_ratio'] || 1.6 }
    c
  end

  def self.view(data)
    v = Object.new
    v.define_singleton_method(:camera) { Builders.camera(data['camera'] || {}) }
    v
  end

  def self.model(data)
    m = Object.new
    m.define_singleton_method(:guid)        { data['guid'] || '' }
    m.define_singleton_method(:title)       { data['title'] || '' }
    m.define_singleton_method(:path)        { data['path'] || '' }
    m.define_singleton_method(:entities)    { Builders.entities(data['entities'] || []) }
    m.define_singleton_method(:materials)   { (data['materials'] || []).map { |d| Builders.material(d) } }
    m.define_singleton_method(:layers)      { (data['layers'] || []).map { |d| Builders.layer(d) } }
    m.define_singleton_method(:definitions) { (data['definitions'] || []).map { |d| Builders.definition(d) } }
    m.define_singleton_method(:active_view) { Builders.view(data) }
    m
  end
end

# ------------------------------------------------------------------
# Main dispatch
# ------------------------------------------------------------------

input  = JSON.parse(STDIN.read)
action = input['action']
md     = input['model'] || {}
m      = Builders.model(md)
es     = SketchupLink::Serializer::EntitySerializer

result = case action
         when 'serialize'
           SketchupLink::Serializer::ModelSerializer.serialize(m)
         when 'serialize_camera'
           SketchupLink::Serializer::ModelSerializer.serialize_camera(Builders.camera(md['camera'] || {}))
         when 'serialize_materials'
           SketchupLink::Serializer::ModelSerializer.serialize_materials(m.materials, es)
         when 'serialize_layers'
           SketchupLink::Serializer::ModelSerializer.serialize_layers(m.layers, es)
         when 'serialize_definitions'
           SketchupLink::Serializer::ModelSerializer.serialize_definitions(m.definitions, es)
         else
           { 'error' => "Unknown action: #{action}" }
         end

puts JSON.generate(result)
