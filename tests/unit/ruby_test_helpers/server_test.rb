# frozen_string_literal: true

require 'json'
require 'socket'

# ------------------------------------------------------------------
# SketchUp API stubs. UI.start_timer defaults to a one-shot timer
# (UI.start_timer(seconds, repeat = false)). run_timers simulates the
# main thread: each call runs every registered timer once, and only
# repeating timers stay registered.
# ------------------------------------------------------------------

module Sketchup
  def self.active_model = nil
  def self.read_default(_section, _key, default) = default
  def self.add_observer(*) = nil
end

module UI
  @timers = {}
  @timer_counter = 0

  class << self
    attr_reader :timers

    def start_timer(_interval, repeat = false, &block)
      @timer_counter += 1
      @timers[@timer_counter] = { repeat: repeat, block: block }
      @timer_counter
    end

    def stop_timer(id)
      @timers.delete(id)
      nil
    end

    def run_timers
      @timers.dup.each do |id, timer|
        timer[:block].call
        @timers.delete(id) unless timer[:repeat]
      end
    end
  end
end

# ------------------------------------------------------------------
# Load real source files, then silence logging so tests do not write
# to the plugin log.
# ------------------------------------------------------------------

$LOAD_PATH.unshift(ENV.fetch('RUBY_PLUGIN_SOURCE'))
require 'sketchup_link/constants'
require 'sketchup_link/logger'
require 'sketchup_link/subscription_manager'
require 'sketchup_link/server'

module SketchupLink
  def self.log(*args, **kwargs); end
  def self.log_error(*args, **kwargs); end
end

# ------------------------------------------------------------------
# Command handling. Each command is {"op": ...}; results align with
# the input order.
# ------------------------------------------------------------------

$server = nil
$socket_path = nil
$sub_mgr = nil
$clients = {}

def try_connect(path)
  UNIXSocket.new(path).close
  true
rescue SystemCallError
  false
end

def read_available(sock)
  out = +''
  while IO.select([sock], nil, nil, 0.2)
    chunk = sock.read_nonblock(65_536, exception: false)
    break if chunk.nil? # EOF
    next if chunk == :wait_readable

    out << chunk
  end
  out
end

def handle(cmd)
  case cmd.fetch('op')
  when 'start'
    $socket_path = cmd.fetch('socket_path')
    $sub_mgr = SketchupLink::SubscriptionManager.new
    $server = SketchupLink::Server.new($sub_mgr)
    $server.start(mode: :unix, socket_path: $socket_path)
    {}
  when 'connect'
    $clients[cmd.fetch('id')] = UNIXSocket.new($socket_path)
    {}
  when 'send'
    $clients.fetch(cmd.fetch('id')).write(cmd.fetch('data'))
    {}
  when 'tick'
    UI.run_timers
    {}
  when 'read'
    { 'data' => read_available($clients.fetch(cmd.fetch('id'))) }
  when 'dispatch'
    $sub_mgr.dispatch(cmd.fetch('event'), cmd.fetch('data'))
    {}
  when 'timers'
    { 'count' => UI.timers.size }
  when 'stop'
    $server.stop
    {}
  when 'try_connect'
    { 'connected' => try_connect($socket_path) }
  else
    raise ArgumentError, "unknown op: #{cmd['op']}"
  end
end

input = JSON.parse(STDIN.read)
commands = input.is_a?(Array) ? input : [input]
results = commands.map { |cmd| handle(cmd) }

$clients.each_value { |sock| sock.close rescue nil }
$server&.stop

print JSON.generate('results' => results)
