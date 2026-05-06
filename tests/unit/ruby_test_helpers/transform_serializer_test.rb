# frozen_string_literal: true

require "json"

# Read column-major matrix from stdin
input = JSON.parse(STDIN.read)
col_major = input.fetch("column_major")

# Mock object that responds to to_a like a Geom::Transformation
mock = Object.new
mock.define_singleton_method(:to_a) { col_major }

# Load the real TransformSerializer
$LOAD_PATH.unshift(ENV.fetch("RUBY_PLUGIN_SOURCE"))
require "sketchup_link/serializer/transform_serializer"

result = SketchupLink::Serializer::TransformSerializer.serialize(mock)

print JSON.generate({ row_major: result })
