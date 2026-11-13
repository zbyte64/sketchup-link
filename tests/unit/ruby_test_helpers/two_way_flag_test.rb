# frozen_string_literal: true

require 'json'
require_relative '../../../sketchup_link/two_way_sync'

commands = JSON.parse($stdin.read)
results = commands.map do |cmd|
  { 'enabled' => SketchupLink::TwoWaySync.enabled?(cmd['value']) }
end
puts JSON.generate({ 'results' => results })
