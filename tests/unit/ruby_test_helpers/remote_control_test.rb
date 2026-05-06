# frozen_string_literal: true

require 'json'

# ------------------------------------------------------------------
# SketchUp API stubs
# ------------------------------------------------------------------

module Geom
  # Stub Geom::Transformation so new(arr).to_a returns arr.
  # Used by RemoteControl.row_major_to_transformation internally.
  class Transformation
    def initialize(arr)
      @arr = arr
    end

    def to_a = @arr
  end
end

# ------------------------------------------------------------------
# Load source files
# ------------------------------------------------------------------

source = ENV.fetch('RUBY_PLUGIN_SOURCE')
serializer_dir = File.join(source, 'sketchup_link/serializer')
$LOAD_PATH << serializer_dir
require 'transform_serializer'

$LOAD_PATH << source
require 'sketchup_link/remote_control'

# ------------------------------------------------------------------
# Main dispatch
# ------------------------------------------------------------------

input = JSON.parse(STDIN.read)
action = input.fetch('action')

result = case action
         when 'roundtrip'
           # Step 1: serialize mock transformation (column-major → row-major meters)
           col_major = input.fetch('column_major')
           mock = Object.new
           mock.define_singleton_method(:to_a) { col_major }
           first = SketchupLink::Serializer::TransformSerializer.serialize(mock)

           # Step 2: row_major_to_transformation (row-major meters → Transformation)
           transformation = SketchupLink::RemoteControl.send(:row_major_to_transformation, first)

           # Step 3: serialize again (Transformation → row-major meters)
           second = SketchupLink::Serializer::TransformSerializer.serialize(transformation)

           { 'roundtripped' => second }
         when 'inverse'
           # row_major_to_transformation → serialize
           row_major = input.fetch('row_major')
           transformation = SketchupLink::RemoteControl.send(:row_major_to_transformation, row_major)
           serialized = SketchupLink::Serializer::TransformSerializer.serialize(transformation)

           { 'result' => serialized }
         else
           { 'error' => "Unknown action: #{action}" }
         end

puts JSON.generate(result)
