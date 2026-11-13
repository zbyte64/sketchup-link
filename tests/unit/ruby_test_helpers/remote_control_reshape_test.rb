# frozen_string_literal: true

require 'json'

# reshape_face must add the new face to the entities that own the old one. A face inside a group or component
# has a ComponentDefinition parent; a loose top-level face has the Model itself as its parent. Neither can
# add_face, so both must be resolved to their entities. Regression guard: top-level faces returned
# "undefined method 'add_face' for Sketchup::Model".

module Geom
  class Point3d
    attr_reader :x, :y, :z
    def initialize(x, y, z) = (@x, @y, @z = x, y, z)
  end
end

module Sketchup
  class Face
    attr_accessor :parent, :material, :back_material, :layer
    attr_reader :persistent_id, :erased
    def initialize(pid) = (@persistent_id = pid)
    def erase! = (@erased = true)
  end

  class Entities
    attr_reader :name, :added
    def initialize(name, items = []) = (@name, @items, @added = name, items, [])
    def each(&block) = @items.each(&block)
    def add_face(points)
      @added << points.map { |p| [p.x, p.y, p.z] }
      Face.new(9000 + @added.length)
    end
  end

  class ComponentDefinition
    attr_reader :entities
    def initialize(entities) = (@entities = entities)
  end

  class Group
    attr_reader :entities
    def initialize(entities) = (@entities = entities)
  end

  class ComponentInstance; end

  class Model
    attr_reader :entities
    def initialize(entities) = (@entities = entities)
    def start_operation(*) = nil
    def commit_operation = nil
    def abort_operation = nil
  end

  class << self
    attr_accessor :active_model
  end
end

module SketchupLink
  def self.log(level, msg, context = {}); end
  def self.log_error(msg, exception, context = {}); end
end

source = ENV.fetch('RUBY_PLUGIN_SOURCE')
$LOAD_PATH << File.join(source, 'sketchup_link/serializer')
require 'transform_serializer'
$LOAD_PATH << source
require 'sketchup_link/remote_control'

loose = Sketchup::Face.new(1)
grouped = Sketchup::Face.new(2)
group_entities = Sketchup::Entities.new('group', [grouped])
definition = Sketchup::ComponentDefinition.new(group_entities)
grouped.parent = definition
top = Sketchup::Entities.new('top', [loose, Sketchup::Group.new(group_entities)])
model = Sketchup::Model.new(top)
loose.parent = model
loose.back_material = 'Blue'
Sketchup.active_model = model

points = [[0, 0, 0], [0.0254, 0, 0], [0.0254, 0.0254, 0]]
input = JSON.parse(STDIN.read)
pid = input.fetch('persistent_id')
status, body = SketchupLink::RemoteControl.handle('geometry/face/reshape', { 'persistent_id' => pid, 'points' => points })
puts JSON.generate({
  'status' => status, 'body' => body,
  'added_to' => [top, group_entities].reject { |e| e.added.empty? }.map(&:name),
  'erased' => [loose, grouped].select(&:erased).map(&:persistent_id)
})
