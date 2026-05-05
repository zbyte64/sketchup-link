# frozen_string_literal: true

require 'socket'
require 'json'

require 'securerandom'
require 'tempfile'
require 'base64'
module SketchupLink
  class Server
    def initialize(subscription_manager)
      @subscription_manager = subscription_manager
      @server  = nil
      @socket_path = nil
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

      # On Windows, IO.select does not support TCP sockets (it only works with
      # pipes).  We must use a background thread with blocking I/O instead of
      # a UI.start_timer-based poll loop.
      @server_thread = Thread.new { server_loop }
    end

    def stop
      @server&.close rescue nil
      @server_thread&.kill if @server_thread&.alive?
      @clients.each { |c| c.close rescue nil }
      @clients.clear
      @buffers.clear
      if ENV['SERVER_MODE'] == 'unix' && @socket_path && File.exist?(@socket_path)
        File.delete(@socket_path)
      end
    rescue StandardError
      # best-effort cleanup
    end

    def server_loop
      loop do
        begin
          client = @server.accept
          Thread.new(client) { |c| handle_client(c) }
        rescue IOError
          break  # server socket closed
        end
      end
    end

    def handle_client(client)
      buffer = +''
      loop do
        begin
          data = client.readpartial(4096)
          buffer << data
          if (idx = buffer.index("\r\n\r\n"))
            header = buffer[0, idx]
            body   = buffer[(idx + 4)..]
            route(client, header, body)
            break
          end
        rescue EOFError, Errno::ECONNRESET, Errno::EPIPE
          break
        end
      end
    rescue => e
      # connection error — client will hang up
    ensure
      client.close rescue nil
    end

    def remove_client(client)
      @subscription_manager.remove_by_socket(client)
      client.close rescue nil
    end

    def route(client, header, _body)
      request_line = header.lines.first.to_s.strip

      case request_line
      when /\AGET \/model(\?|\s|\z)/
        opts = parse_model_params(request_line)
        payload = Serializer::ModelSerializer.serialize(
          Sketchup.active_model,
          Serializer::EntitySerializer,
          no_textures: opts[:no_textures]
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

      when /\APOST \/control\/(.+)(\s|\z)/
        sub_path = Regexp.last_match(1)
        body = _body
        params = begin
                    body.nil? || body.strip.empty? ? {} : JSON.parse(body)
                  rescue JSON::ParserError
                    respond(client, 400, JSON.generate('error' => 'invalid JSON body'))
                    remove_client(client)
                    return
                  end
        status, response = RemoteControl.handle(sub_path, params)
        respond(client, status, JSON.generate(response))
        remove_client(client)

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

    def parse_model_params(request_line)
      opts = { no_textures: false }
      query = request_line.split('?', 2).last.to_s.strip
      return opts if query.empty? || query.include?('HTTP/')
      query.split('&').each do |param|
        key, value = param.split('=', 2)
        next unless key
        case key
        when 'no_textures'
          opts[:no_textures] = value == 'true'
        end
      end
      opts
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
      # Base64-encoded 4x4 red-white checkerboard PNG
      checker_png_b64 = 'iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAF0lEQVR4nGP4z8DwHwjAJIIFJBlwygAARRkf4WJ1tmcAAAAASUVORK5CYII='
      begin
        tmp = Tempfile.new(['sketchup_texture', '.png'])
        tmp_path = tmp.path
        tmp.binmode
        tmp.write(Base64.decode64(checker_png_b64))
        tmp.close
        red_mat.texture = tmp_path
      rescue StandardError => e
        SketchupLink.log("Failed to set test texture: #{e.message}")
      ensure
        File.delete(tmp_path) if tmp_path && File.exist?(tmp_path)
      end

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
