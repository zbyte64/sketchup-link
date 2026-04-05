# frozen_string_literal: true

require 'socket'
require 'json'

module SketchupLink
  class Server
    def initialize(subscription_manager)
      @subscription_manager = subscription_manager
      @server  = nil
      @clients = []
      @buffers = {}
      @socket_path = nil
      @timer_id    = nil
    end

    def start(socket_path)
      @socket_path = socket_path
      File.delete(socket_path) if File.exist?(socket_path)
      @server = UNIXServer.new(socket_path)
      @timer_id = UI.start_timer(TIMER_INTERVAL, true) do
        tick
      rescue IOError, Errno::EBADF
        # socket already closed — will be cleaned up next tick
      end
    end

    def stop
      UI.stop_timer(@timer_id) if @timer_id
      @clients.each { |c| c.close rescue nil }
      @clients.clear
      @buffers.clear
      @server&.close rescue nil
      File.delete(@socket_path) if @socket_path && File.exist?(@socket_path)
    rescue StandardError
      # best-effort cleanup
    end

    private

    def tick
      all = [@server] + @clients
      readable, = IO.select(all, nil, nil, 0)
      return unless readable

      readable.each do |s|
        if s == @server
          accept_client
        else
          read_client(s)
        end
      end
    end

    def accept_client
      client = @server.accept_nonblock
      @clients << client
      @buffers[client] = +''
    rescue IO::WaitReadable
      # no connection ready yet
    end

    def read_client(client)
      data = client.read_nonblock(4096)
      @buffers[client] << data
      if (idx = @buffers[client].index("\r\n\r\n"))
        header   = @buffers[client][0, idx]
        body     = @buffers[client][(idx + 4)..]
        @buffers.delete(client)
        route(client, header, body)
      end
    rescue IO::WaitReadable
      # nothing to read right now
    rescue EOFError, Errno::ECONNRESET, Errno::EPIPE
      remove_client(client)
    end

    def remove_client(client)
      @clients.delete(client)
      @buffers.delete(client)
      @subscription_manager.remove_by_socket(client)
      client.close rescue nil
    end

    def route(client, header, _body)
      request_line = header.lines.first.to_s.strip

      case request_line
      when /\AGET \/model(\s|\z)/
        payload = Serializer::ModelSerializer.serialize(
          Sketchup.active_model,
          Serializer::EntitySerializer
        )
        respond(client, 200, JSON.generate(payload))
        remove_client(client)

      when /\AGET \/status(\s|\z)/
        respond(client, 200, JSON.generate(@subscription_manager.status))
        remove_client(client)

      when /\AGET \/subscribe(\?|\s|\z)/
        events = parse_events_param(request_line)
        id = @subscription_manager.subscribe(client, events)
        begin
          client.write(
            "HTTP/1.1 200 OK\r\n" \
            "Content-Type: application/x-ndjson\r\n" \
            "Transfer-Encoding: chunked\r\n" \
            "Connection: keep-alive\r\n\r\n"
          )
          client.write(make_chunk(JSON.generate('subscription_id' => id) + "\n"))
          client.flush
        rescue Errno::EPIPE, IOError
          remove_client(client)
        end
        # client stays in @clients — events streamed by subscription_manager

      when /\ADELETE \/unsubscribe\/([^\s\/]+)/
        sub_id = Regexp.last_match(1)
        @subscription_manager.unsubscribe(sub_id)
        respond(client, 200, JSON.generate('ok' => true))
        remove_client(client)

      else
        respond(client, 404, JSON.generate('error' => 'not found'))
        remove_client(client)
      end
    end

    def respond(client, status, body)
      status_text = status == 200 ? 'OK' : 'Not Found'
      client.write(
        "HTTP/1.1 #{status} #{status_text}\r\n" \
        "Content-Type: application/json\r\n" \
        "Content-Length: #{body.bytesize}\r\n" \
        "Connection: close\r\n\r\n" \
        "#{body}"
      )
      client.flush
    rescue Errno::EPIPE, IOError
      remove_client(client)
    end

    def make_chunk(data)
      "#{data.bytesize.to_s(16)}\r\n#{data}\r\n"
    end

    def parse_events_param(request_line)
      return ['*'] unless request_line =~ /events=([^&\s]+)/

      Regexp.last_match(1).split(',').map(&:strip).reject(&:empty?)
    end
  end
end
