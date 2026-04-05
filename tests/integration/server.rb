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

# Build the model JSON once — same snapshot for every connection in the test run.
MODEL_JSON = JSON.generate(Factories.test_model).freeze

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

  if request_line.start_with?('GET /model')
    respond(client, 200, MODEL_JSON)
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
