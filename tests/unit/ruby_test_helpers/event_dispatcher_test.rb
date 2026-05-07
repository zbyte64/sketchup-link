# frozen_string_literal: true

require 'json'

# ------------------------------------------------------------------
# SketchUp API stubs — defined before requiring source files
# ------------------------------------------------------------------

module Sketchup
  def self.active_model
    $test_model
  end
end

module UI
  @@timers = {}
  @@timer_counter = 0

  def self.start_timer(_interval, &block)
    @@timer_counter += 1
    id = @@timer_counter
    @@timers[id] = proc {
      @@timers.delete(id)
      block.call
    }
    id
  end

  def self.stop_timer(id)
    @@timers.delete(id)
  end

  # Testing helpers
  def self.run_all_timers
    ids = @@timers.keys.sort
    ids.each { |id| @@timers[id]&.call }
  end

  def self.clear_timers
    @@timers.clear
  end

  def self.timer_count
    @@timers.size
  end
end

# ------------------------------------------------------------------
# Stub Serializer::EntitySerializer before loading source files
# ------------------------------------------------------------------

module SketchupLink
  module Serializer
    class EntitySerializer
      def self.serialize(entity)
        {
          'persistent_id' => entity.respond_to?(:persistent_id) ? entity.persistent_id : entity.entityID
        }
      end

      def self.serialize_entities(entities)
        entities.map { |e| serialize(e) }
      end
    end
  end
end

# Stub logging — no log file in test mode
module SketchupLink
  def self.log(level, msg, context = {}); end
  def self.log_error(msg, exception, context = {}); end
end


# ------------------------------------------------------------------
# Load real source files
# ------------------------------------------------------------------

$LOAD_PATH.unshift(ENV.fetch('RUBY_PLUGIN_SOURCE'))
require 'sketchup_link/constants'
require 'sketchup_link/subscription_manager'
require 'sketchup_link/event_dispatcher'

# ------------------------------------------------------------------
# Mock subscription manager — captures dispatched events
# ------------------------------------------------------------------


class MockSubscriptionManager
  attr_reader :events

  def initialize
    @events = []
  end

  def dispatch(event, payload)
    @events << { 'event' => event, 'payload' => payload }
  end
end

# ------------------------------------------------------------------
# Shared state across commands
# ------------------------------------------------------------------

$dispatcher = nil
$mock_sub_mgr = nil
$test_model = nil

# ------------------------------------------------------------------
# Stub builders
# ------------------------------------------------------------------

def build_model(data)
  model = Object.new
  model.define_singleton_method(:guid)      { data['guid'] || 'test-guid' }
  model.define_singleton_method(:title)     { data['title'] || 'Test Model' }

  selection = (data['selection'] || []).map { |ed| build_entity(ed) }
  model.define_singleton_method(:selection) { selection }
  model
end

def build_entity(data)
  pid  = data['persistent_id']
  eid  = data['entityID']
  name = data['type'] || 'Entity'

  e = Object.new
  valid = data.key?('valid') ? data['valid'] : true
  e.define_singleton_method(:valid?) { valid }
  e.define_singleton_method(:persistent_id) { pid }
  e.define_singleton_method(:entityID)  { eid || pid }
  e.define_singleton_method(:to_s)      { "#{name}(pid=#{pid})" }
  e
end

# ------------------------------------------------------------------
# Command dispatcher
# ------------------------------------------------------------------

def handle_command(cmd)
  action = cmd['action']

  case action

  when 'create'
    $mock_sub_mgr = MockSubscriptionManager.new
    $dispatcher   = SketchupLink::EventDispatcher.new($mock_sub_mgr)
    $test_model   = nil
    UI.clear_timers
    { 'status' => 'ok' }

  when 'set_model'
    $test_model = build_model(cmd['model'] || {})
    { 'status' => 'ok' }

  when 'transaction_start'
    $dispatcher.on_transaction_start
    { 'status' => 'ok' }

  when 'transaction_commit'
    model = $test_model || build_model(cmd['model'] || {})
    $dispatcher.on_transaction_commit(model)
    { 'status' => 'ok' }

  when 'transaction_abort'
    model = $test_model || build_model(cmd['model'] || {})
    $dispatcher.on_transaction_abort(model)
    { 'status' => 'ok' }

  when 'transaction_undo'
    model = $test_model || build_model(cmd['model'] || {})
    $dispatcher.on_transaction_undo(model)
    { 'status' => 'ok' }

  when 'transaction_redo'
    model = $test_model || build_model(cmd['model'] || {})
    $dispatcher.on_transaction_redo(model)
    { 'status' => 'ok' }

  when 'entity_added'
    $dispatcher.on_entity_added(build_entity(cmd['entity']))
    { 'status' => 'ok' }

  when 'entity_modified'
    $dispatcher.on_entity_modified(build_entity(cmd['entity']))
    { 'status' => 'ok' }

  when 'entity_removed'
    if cmd['entity_id'].is_a?(Integer)
      $dispatcher.on_entity_removed(cmd['entity_id'])
    else
      $dispatcher.on_entity_removed(build_entity(cmd['entity_id']))
    end
    { 'status' => 'ok' }

  when 'selection_change'
    if cmd['model']
      $dispatcher.on_selection_change(build_model(cmd['model']))
    else
      model = $test_model || build_model({})
      $dispatcher.on_selection_change(model)
    end
    { 'status' => 'ok' }

  when 'materials_change'
    model = $test_model || build_model(cmd['model'] || {})
    $dispatcher.on_materials_change(model)
    { 'status' => 'ok' }

  when 'layers_change'
    model = $test_model || build_model(cmd['model'] || {})
    $dispatcher.on_layers_change(model)
    { 'status' => 'ok' }

  when 'model_save'
    model = $test_model || build_model(cmd['model'] || {})
    $dispatcher.on_model_save(model)
    { 'status' => 'ok' }

  when 'model_open'
    model = $test_model || build_model(cmd['model'] || {})
    $dispatcher.on_model_open(model)
    { 'status' => 'ok' }

  when 'model_close'
    model = $test_model || build_model(cmd['model'] || {})
    $dispatcher.on_model_close(model)
    { 'status' => 'ok' }

  when 'run_timers'
    UI.run_all_timers
    { 'status' => 'ok' }

  when 'get_timers'
    { 'timer_count' => UI.timer_count }

  when 'get_events'
    { 'events' => ($mock_sub_mgr&.events || []).dup, 'status' => 'ok' }

  when 'clear_events'
    $mock_sub_mgr&.events&.clear
    { 'status' => 'ok' }

  when 'reset'
    $dispatcher     = nil
    $mock_sub_mgr   = nil
    $test_model     = nil
    UI.clear_timers
    { 'status' => 'ok' }

  else
    { 'error' => "Unknown action: #{action}" }
  end
end

# ------------------------------------------------------------------
# Main — accept array of commands or single command
# ------------------------------------------------------------------

input = JSON.parse(STDIN.read)
commands = input.is_a?(Array) ? input : [input]

results = commands.map { |cmd| handle_command(cmd) }

output = {
  'commands' => results,
  'events'   => ($mock_sub_mgr&.events || []).dup,
  'timers'   => UI.timer_count
}
STDERR.puts "event_dispatcher_test: processed #{commands.length} command(s), #{output['events'].length} event(s) captured"
print JSON.generate(output)
