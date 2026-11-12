# frozen_string_literal: true

require 'json'

# Contract tests for RemoteControl.handle: every route must answer [status, body].
# Success handlers return a bare hash; handle must wrap it as [200, hash]. Error
# handlers return [status, body] and must pass through unchanged.

module Geom
  class Transformation
    def initialize(arr) = @arr = arr
    def to_a = @arr
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

input = JSON.parse(STDIN.read)
route = input.fetch('route')
stub_kind = input.fetch('stub_kind')
handler = {
  'camera' => :set_camera,
  'layer' => :set_layer
}.fetch(route, nil)

if handler && stub_kind
  stubbed_return = stub_kind == 'hash' ? { 'ok' => true } : [400, { 'error' => 'stubbed' }]
  SketchupLink::RemoteControl.define_singleton_method(handler) { |_params| stubbed_return }
end

status, body = SketchupLink::RemoteControl.handle(route, {})
puts JSON.generate({ 'status' => status, 'body' => body })
