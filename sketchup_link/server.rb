# frozen_string_literal: true

require 'socket'
require 'json'

require 'securerandom'
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
      if ENV['SERVER_MODE'] == 'unix'
        File.delete(socket_path) if File.exist?(socket_path)
        @server = UNIXServer.new(socket_path)
      else
        # Default to TCP mode — no env var needed when running in the VM
        port = (ENV['TCP_PORT'] || DEFAULT_TCP_PORT).to_i
        @server = TCPServer.new('0.0.0.0', port)
      end
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
      if ENV['SERVER_MODE'] == 'unix' && @socket_path && File.exist?(@socket_path)
        File.delete(@socket_path)
      end
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

      when /\AGET \/screenshot(\?|\s|\z)/
        if Sketchup.active_model
          width, height = parse_screenshot_params(request_line)
          temp_path = File.join(ENV['TEMP'] || ENV['TMP'] || '/tmp', "sketchup_screenshot_#{SecureRandom.hex}.png")
          begin
            view = Sketchup.active_model.active_view
            view.write_image(temp_path, width, height, true, 0.9)
            png_data = File.binread(temp_path)
            respond_binary(client, 200, png_data, 'image/png')
          rescue => e
            respond(client, 500, JSON.generate('error' => "screenshot failed: #{e.message}"))
          ensure
            File.delete(temp_path) rescue nil
          end
        else
          respond(client, 400, JSON.generate('error' => 'no active model'))
        end
        remove_client(client)
      when /\APOST \/test_model(\s|\z)/
        model = Sketchup.active_model
        unless model
          respond(client, 400, JSON.generate('error' => 'no active model'))
          remove_client(client)
        else
          begin
            model.start_operation('Create Test Model', true)
            create_test_model_from_factories(model)
            model.commit_operation
            respond(client, 200, JSON.generate('ok' => true))
          rescue => e
            model.abort_operation
            respond(client, 500, JSON.generate('error' => e.message))
          end
          remove_client(client)
        end

      else
        respond(client, 404, JSON.generate('error' => 'not found'))
        remove_client(client)
      end
    end

    def respond_binary(client, status, data, content_type)
      status_text = status == 200 ? 'OK' : 'Internal Server Error'
      client.write(
        "HTTP/1.1 #{status} #{status_text}\r\n" \
        "Content-Type: #{content_type}\r\n" \
        "Content-Length: #{data.bytesize}\r\n" \
        "Connection: close\r\n\r\n"
      )
      client.write(data)
      client.flush
    rescue Errno::EPIPE, IOError
      remove_client(client)
    end
    def parse_screenshot_params(request_line)
      width = 1920
      height = 1080
      query = request_line.split('?', 2).last.to_s.strip
      return [width, height] if query.empty?
      query.split('&').each do |param|
        key, value = param.split('=', 2)
        width = value.to_i if key == 'width' && value.match?(/\A\d+\z/)
        height = value.to_i if key == 'height' && value.match?(/\A\d+\z/)
      end
      [width, height]
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
    # Creates the canonical test model matching tests/integration/factories.rb spec.
    # Called by POST /test_model.
    def create_test_model_from_factories(model)
      # Layers
      furniture_layer = model.layers.add('Furniture')
      hidden_layer = model.layers.add('Hidden')
      hidden_layer.visible = false

      # Materials
      red_mat = model.materials.add('Red')
      red_mat.color = Sketchup::Color.new(220, 20, 20)
      blue_mat = model.materials.add('Blue')
      blue_mat.color = Sketchup::Color.new(20, 20, 200)

      size  = 2.0
      y_off = 0.0

      # --- Top-level entity [0]: Face with front material Red ---
      pts1 = [[-size, y_off - size, 0], [size, y_off - size, 0],
              [size, y_off + size, 0], [-size, y_off + size, 0]]
      face1 = model.entities.add_face(pts1)
      face1.material = red_mat

      # --- Top-level entity [1]: Face with back material Blue ---
      pts2 = [[-size + 6, y_off - size, 0], [size + 6, y_off - size, 0],
              [size + 6, y_off + size, 0], [-size + 6, y_off + size, 0]]
      face2 = model.entities.add_face(pts2)
      face2.back_material = blue_mat

      # --- Top-level entity [2]: Edge ---
      edge = model.entities.add_line([0, y_off - 1, 1], [2, y_off + 1, 1])

      # --- Top-level entity [3]: Group 'FurnitureGroup' on layer Furniture ---
      group = model.entities.add_group
      group.name = 'FurnitureGroup'
      group.layer = furniture_layer
      gpts = [[-size, -size, 0], [size, -size, 0],
              [size, size, 0], [-size, size, 0]]
      gface = group.entities.add_face(gpts)
      gface.layer = furniture_layer
      gedge = group.entities.add_line([0, -1, 1], [2, 1, 1])
      gedge.layer = furniture_layer

      # --- Component definition 'Chair' with 2 faces ---
      chair_def = model.definitions.add('Chair')
      cpts1 = [[-size, -size + 4, 0], [size, -size + 4, 0],
               [size, size + 4, 0], [-size, size + 4, 0]]
      chair_def.entities.add_face(cpts1)
      cpts2 = [[-size + 6, -size + 4, 0], [size + 6, -size + 4, 0],
               [size + 6, size + 4, 0], [-size + 6, size + 4, 0]]
      chair_def.entities.add_face(cpts2)

      # --- Top-level entity [4]: ComponentInstance on layer Furniture ---
      inst = model.entities.add_instance(chair_def, Geom::Transformation.new)
      inst.layer = furniture_layer
    end

  end
end
