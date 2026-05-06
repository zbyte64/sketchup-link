#!/usr/bin/env ruby
# frozen_string_literal: true
# tests/integration/server.rb
#
# Standalone HTTP-over-Unix-socket server for integration testing.
# No SketchUp, no gems — pure stdlib (socket, json, securerandom via factories).
#
# Usage:  ruby tests/integration/server.rb <socket_path>
#
# Lifecycle:
#   1. Builds MODEL_JSON from Factories.test_model (randomized but structurally fixed).
#   2. Removes any stale socket file.
#   3. Writes "ready\n" to stdout and flushes — pytest fixture blocks on this.
#   4. Accepts connections and serves GET /model until SIGTERM/SIGINT.
#   5. Trap handlers close the server socket and delete the socket file before exit.

require 'socket'
require 'json'
require_relative 'factories'

SOCKET_PATH = ARGV[0] || '/tmp/sketchup-link-test.sock'

# Build model JSON twice: full and no-textures variant.
MODEL_JSON         = JSON.generate(Factories.test_model).freeze
MODEL_JSON_NO_TEX  = JSON.generate(Factories.test_model_no_textures).freeze
# ---------------------------------------------------------------------------
# HTTP helpers (defined before the accept loop)
# ---------------------------------------------------------------------------

def respond(client, status, body)
  status_text = status == 200 ? 'OK' : 'Not Found'
  client.write(
    "HTTP/1.1 #{status} #{status_text}\r\n" \
    "Content-Type: application/json\r\n"    \
    "Content-Length: #{body.bytesize}\r\n"  \
    "Connection: close\r\n"                 \
    "\r\n"                                  \
    "#{body}"
  )
  client.flush
rescue Errno::EPIPE, IOError
  # client disconnected — ignore
end

# ---------------------------------------------------------------------------
# Mock remote control handlers
# ---------------------------------------------------------------------------

def parse_json_body(client, body_json)
  return {} if body_json.nil? || body_json.strip.empty?
  JSON.parse(body_json)
rescue JSON::ParserError
  respond(client, 400, JSON.generate({ 'error' => 'invalid JSON body' }))
  nil
end

def handle_control(client, path, body_json)
  params = parse_json_body(client, body_json)
  return unless params  # parse error already responded

  sub_path = path.sub(%r{^/control/}, '')
  response = control_mock_response(sub_path, params)
  respond(client, response[0], JSON.generate(response[1]))
end

def control_mock_response(sub_path, params)
  case sub_path
  # Camera
  when 'camera'
    required = %w[eye target up]
    missing = required.select { |k| params[k].nil? }
    return [400, { 'error' => "missing required field: #{missing.first}" }] unless missing.empty?
    [200, { 'ok' => true }]

  when 'camera/zoom'
    return [400, { 'error' => 'missing required field: factor' }] unless params['factor']
    [200, { 'ok' => true }]

  # Layers
  when 'layer'
    return [400, { 'error' => 'missing required field: name' }] unless params['name']
    [200, { 'ok' => true }]

  # Plugins
  when 'plugin'
    return [400, { 'error' => 'missing required field: name' }] unless params['name']
    return [400, { 'error' => 'missing required field: enabled' }] if params['enabled'].nil?
    return [404, { 'error' => "extension not found: #{params['name']}" }] if params['name'] == 'NonExistentExtension'
    [200, { 'ok' => true, 'note' => 'extension changes may require a SketchUp restart' }]

  # Texture
  when 'texture'
    return [400, { 'error' => 'missing required field: material_name' }] unless params['material_name']
    return [400, { 'error' => 'missing required field: file_path' }] unless params['file_path']
    return [400, { 'error' => "texture file not found: #{params['file_path']}" }] unless File.exist?(params['file_path'])
    [200, { 'ok' => true, 'material' => { 'name' => params['material_name'], 'texture' => params['file_path'] } }]

  # Material
  when 'material'
    return [400, { 'error' => 'missing required field: name' }] unless params['name']
    [200, { 'ok' => true }]

  when 'material/delete'
    return [400, { 'error' => 'missing required field: name' }] unless params['name']
    [200, { 'ok' => true }]

  # Geometry
  when 'geometry/face'
    return [400, { 'error' => 'missing required field: points' }] unless params['points']
    [200, { 'ok' => true, 'persistent_id' => 42_001 }]

  when 'geometry/edge'
    return [400, { 'error' => 'missing required field: start' }] unless params['start']
    return [400, { 'error' => 'missing required field: end' }] unless params['end']
    [200, { 'ok' => true, 'persistent_id' => 42_002 }]

  when 'geometry/group'
    [200, { 'ok' => true, 'persistent_id' => 42_003 }]

  when 'geometry/component'
    return [400, { 'error' => 'missing required field: definition_name' }] unless params['definition_name']
    [200, { 'ok' => true, 'persistent_id' => 42_004 }]

  when 'geometry/delete'
    return [400, { 'error' => 'missing required field: persistent_id' }] unless params['persistent_id']
    [200, { 'ok' => true }]

  when 'geometry/transform'
    return [400, { 'error' => 'missing required field: persistent_id' }] unless params['persistent_id']
    return [400, { 'error' => 'missing required field: transformation' }] unless params['transformation']
    [200, { 'ok' => true }]

  # Model
  when 'model/clear'
    [200, { 'ok' => true }]

  when 'model/new'
    [200, { 'ok' => true }]

  else
    [404, { 'error' => "unknown control path: #{sub_path}" }]
  end
end
def handle_client(client)
  buf = +''
  loop do
    begin
      chunk = client.read_nonblock(4096)
      buf << chunk
      break if buf.include?("\r\n\r\n")
    rescue IO::WaitReadable
      ready = IO.select([client], nil, nil, 5)
      break unless ready  # timeout — close without response
      retry
    rescue EOFError, Errno::ECONNRESET
      break
    end
  end

  request_line = buf.lines.first.to_s.strip
  method = request_line.split(' ').first || 'GET'
  path = request_line.split(' ')[1] || '/'
  path_no_query = path.split('?').first

  if method == 'GET' && path_no_query == '/model'
    # no_textures=true strips texture binary data
    if path.include?('no_textures=true')
      respond(client, 200, MODEL_JSON_NO_TEX)
    else
      respond(client, 200, MODEL_JSON)
    end
  elsif method == 'POST' && path.start_with?('/control/')
    # Extract the body after headers
    body_start = buf.index("\r\n\r\n")
    body_json = body_start ? buf[(body_start + 4)..] : ''
    handle_control(client, path, body_json)
  elsif method == 'POST' && path_no_query == '/log'
    # Extract body and log to stderr for test diagnosis
    body_start = buf.index("\r\n\r\n")
    body_json = body_start ? buf[(body_start + 4)..] : ''
    log_entry = begin
      JSON.parse(body_json)
    rescue JSON::ParserError
      { 'raw' => body_json }
    end
    $stderr.puts "[TEST-LOG] #{JSON.generate(log_entry)}"
    $stderr.flush
    respond(client, 200, JSON.generate({ 'ok' => true }))
  else
    respond(client, 404, JSON.generate({ 'error' => 'not found' }))
  end
ensure
  client.close rescue nil
end

# ---------------------------------------------------------------------------
# Server startup
# ---------------------------------------------------------------------------

File.delete(SOCKET_PATH) if File.exist?(SOCKET_PATH)

server = UNIXServer.new(SOCKET_PATH)

# Signal pytest conftest that the socket is ready to accept connections.
$stdout.puts 'ready'
$stdout.flush

# Graceful shutdown: close the server socket so accept raises IOError/EBADF,
# then delete the socket file before exiting.
shutdown = proc do
  server.close rescue nil
  File.delete(SOCKET_PATH) rescue nil
  exit 0
end
trap('TERM', &shutdown)
trap('INT',  &shutdown)

# ---------------------------------------------------------------------------
# Accept loop
# ---------------------------------------------------------------------------

loop do
  begin
    client = server.accept
  rescue IOError, Errno::EBADF
    # Server socket was closed by the signal trap — exit cleanly.
    break
  end

  handle_client(client)
end
