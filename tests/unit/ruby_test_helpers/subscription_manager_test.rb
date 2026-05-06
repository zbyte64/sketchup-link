# frozen_string_literal: true

# ------------------------------------------------------------------
# SketchUp API stub — SubscriptionManager#status references
# Sketchup.active_model, which does not exist outside SketchUp.
# ------------------------------------------------------------------

module Sketchup
  def self.active_model
    nil
  end
end
require 'stringio'

# ------------------------------------------------------------------
# Load real source files
# ------------------------------------------------------------------

$LOAD_PATH.unshift(ENV.fetch('RUBY_PLUGIN_SOURCE'))
require 'sketchup_link/constants'
require 'sketchup_link/subscription_manager'

# ------------------------------------------------------------------
# Socket mocks
# ------------------------------------------------------------------

# A live socket that records every payload passed to #write.
class MockSocket < StringIO
  attr_reader :writes

  def initialize
    super
    @writes = []
  end

  def write(data)
    @writes << data
    super
  end

  def flush; end
end

# A dead socket whose #write always raises EPIPE.
class DeadSocket
  def write(_data)
    raise Errno::EPIPE, 'Broken pipe'
  end

  def flush; end
  def close; end
end

# ------------------------------------------------------------------
# Shared state across commands
# ------------------------------------------------------------------

$manager = nil
$mock_sockets = nil

# ------------------------------------------------------------------
# Command dispatcher
# ------------------------------------------------------------------

def handle_command(cmd)
  action = cmd['action']

  case action

  when 'subscribe'
    sock = MockSocket.new
    $mock_sockets << sock
    id = $manager.subscribe(sock, cmd['events'])
    { 'ok' => true, 'id' => id, 'uuid_random' => true }

  when 'unsubscribe'
    $manager.unsubscribe(cmd['id'])
    { 'ok' => true, 'count_after' => $manager.status['subscriptions'] }

  when 'unsubscribe_nonexistent'
    $manager.unsubscribe(cmd['id'])
    { 'ok' => true, 'count_after' => $manager.status['subscriptions'] }

  when 'dispatch'
    $manager.dispatch(cmd['event'], cmd['payload'])
    writes = $mock_sockets.flat_map(&:writes)
    { 'ok' => true, 'writes' => writes }

  when 'dispatch_dead'
    sock = DeadSocket.new
    $manager.subscribe(sock, [cmd['event']])
    count_before = $manager.status['subscriptions']
    $manager.dispatch(cmd['event'], cmd['payload'])
    count_after = $manager.status['subscriptions']
    { 'ok' => true, 'cleaned' => count_after < count_before, 'count_before' => count_before, 'count_after' => count_after }

  when 'remove_by_socket'
    idx = cmd['socket_index']
    sock = $mock_sockets[idx]
    $manager.remove_by_socket(sock)
    { 'ok' => true }

  when 'status'
    $manager.status

  when 'matches'
    result = $manager.send(:matches?, cmd['events'], cmd['event'])
    { 'ok' => true, 'result' => result }

  when 'make_chunk'
    chunk = $manager.send(:make_chunk, cmd['data'])
    { 'ok' => true, 'chunk' => chunk }

  else
    { 'error' => "Unknown action: #{action}" }
  end
end

# ------------------------------------------------------------------
# Main — accepts an array of commands
# ------------------------------------------------------------------

input = JSON.parse(STDIN.read)
commands = input.is_a?(Array) ? input : [input]

$manager = ::SketchupLink::SubscriptionManager.new
$mock_sockets = []

results = commands.map { |cmd| handle_command(cmd) }

STDERR.puts "subscription_manager_test: processed #{commands.length} command(s)"
puts JSON.generate(results)
