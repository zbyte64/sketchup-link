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
      @mode    = nil
      @tcp_port = nil
      @tick_id = nil
      @pending = {} # client socket => partial request buffer, until routed or closed
    end

    def start(config = {})
      @mode = config[:mode] || (ENV['SERVER_MODE'] == 'unix' ? :unix : :tcp)
      @socket_path = config[:socket_path] || DEFAULT_SOCKET_PATH
      @tcp_port = (config[:tcp_port] || ENV['TCP_PORT'] || DEFAULT_TCP_PORT).to_i
      if @mode == :unix
        begin
          File.delete(@socket_path) if File.exist?(@socket_path)
          @server = UNIXServer.new(@socket_path)
        rescue StandardError => e
          # Unix-first with TCP fallback: if the socket cannot be bound, serve over TCP instead.
          SketchupLink.log(:warn, 'Unix socket bind failed, falling back to TCP', socket_path: @socket_path, error: e.message)
          @mode = :tcp
          @server = TCPServer.new('0.0.0.0', @tcp_port)
        end
      else
        @server = TCPServer.new('0.0.0.0', @tcp_port)
      end
      # SketchUp's embedded Ruby does not run background threads while the main thread
      # idles in its UI loop, so requests are serviced by a main-thread timer instead.
      UI.stop_timer(@tick_id) if @tick_id
      @tick_id = UI.start_timer(TIMER_INTERVAL, true) { tick }
      SketchupLink.log(:info, 'Server started', mode: @mode, socket_path: @socket_path, tcp_port: @tcp_port)
    end

    def stop
      SketchupLink.log(:info, 'Server stopped')
      UI.stop_timer(@tick_id) if @tick_id
      @tick_id = nil
      @server&.close rescue nil
      @pending.each_key { |client| client.close rescue nil }
      @pending.clear
      if @mode == :unix && @socket_path && File.exist?(@socket_path)
        File.delete(@socket_path)
      end
    rescue StandardError => e
      SketchupLink.log_error('Error stopping server', e)
    end

    # Runs on the SketchUp main thread every TIMER_INTERVAL seconds.
    def tick
      accept_pending
      service_pending
    rescue StandardError => e
      SketchupLink.log_error('Server tick failed', e)
    end

    def accept_pending
      loop do
        client = @server.accept_nonblock
        @pending[client] = +''
      rescue IO::WaitReadable
        break
      end
    end

    def service_pending
      readable, = IO.select(@pending.keys, nil, nil, 0)
      return unless readable

      readable.each { |client| service_client(client) }
    end

    def service_client(client)
      buffer = @pending[client]
      buffer << client.read_nonblock(4096)
      idx = buffer.index("\r\n\r\n")
      return unless idx

      @pending.delete(client)
      result = route(client, buffer[0, idx], buffer[(idx + 4)..], request_id: SecureRandom.uuid)
      return if result == :subscribed

      client.close rescue nil
    rescue IO::WaitReadable
      nil
    rescue EOFError, Errno::ECONNRESET, Errno::EPIPE, IOError => e
      SketchupLink.log(:info, 'Client read error', error: e.message)
      @pending.delete(client)
      client.close rescue nil
    rescue StandardError => e
      SketchupLink.log_error('Client request failed', e)
      @pending.delete(client)
      client.close rescue nil
    end

    def remove_client(client)
      @subscription_manager.remove_by_socket(client)
      client.close rescue nil
    end

    def route(client, header, _body, request_id: nil)
      request_line = header.lines.first.to_s.strip
      start_time = Time.now

      case request_line
      when /\AGET \/model(\?|\s|\z)/
        opts = parse_model_params(request_line)
        payload = Serializer::ModelSerializer.serialize(
          Sketchup.active_model,
          Serializer::EntitySerializer,
          no_textures: opts[:no_textures],
          binary_textures: opts[:binary_textures]
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
        :subscribed
        # subscriber socket stays open: subscription_manager streams events to it from the main thread

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
      when /\AGET \/texture\/([^\s\/]+)/
        texture_name = Regexp.last_match(1)
        model = Sketchup.active_model
        unless model
          respond(client, 400, JSON.generate('error' => 'no active model'))
          remove_client(client)
          return
        end
        material = model.materials[texture_name]
        unless material && material.texture
          respond(client, 404, JSON.generate('error' => "texture not found for material: #{texture_name}"))
          remove_client(client)
          return
        end
        begin
          tex = material.texture
          tmp = Tempfile.new(['sketchup_texture', '.png'])
          tmp_path = tmp.path
          tmp.close
          tex.write(tmp_path)
          png_data = File.binread(tmp_path)
          respond_binary(client, 200, png_data, 'image/png')
        rescue => e
          respond(client, 500, JSON.generate('error' => "texture fetch failed: #{e.message}"))
        ensure
          File.delete(tmp_path) rescue nil
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

      when /\APOST \/control\/(\S+)/
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
      when /\APOST \/log(\s|\z)/
        body = _body
        log_entry = begin
                       body.nil? || body.strip.empty? ? {} : JSON.parse(body)
                     rescue JSON::ParserError
                       { 'raw' => body }
                     end
        SketchupLink.log(:info, 'API log', log_entry: log_entry)
        respond(client, 200, JSON.generate('ok' => true))
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
    rescue Errno::EPIPE, IOError => e
      SketchupLink.log(:info, 'Binary response write error', error: e.message)
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
    rescue Errno::EPIPE, IOError => e
      SketchupLink.log(:info, 'Response write error', error: e.message)
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
        when 'binary_textures'
          opts[:binary_textures] = value == 'true'
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
        SketchupLink.log_error('Failed to set test texture', e)
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

      # --- Top-level entity [5]: VisualCube, a large cube whose every face is Blue ---
      # Appended after the existing entities so their indices do not move. It sits clear
      # of the other geometry so a material or transform change on it is visible in a
      # viewport capture. Used by the visual checks in tests/integration.
      visual = model.entities.add_group
      visual.name = 'VisualCube'
      vs = 6.0
      vx = 20.0
      corners = [[vx - vs, -vs, 0], [vx + vs, -vs, 0], [vx + vs, vs, 0], [vx - vs, vs, 0]]
      top = [[vx - vs, -vs, 2 * vs], [vx + vs, -vs, 2 * vs], [vx + vs, vs, 2 * vs], [vx - vs, vs, 2 * vs]]
      visual.entities.add_face(corners).material = blue_mat
      visual.entities.add_face(top).material = blue_mat
      [[0, 1], [1, 2], [2, 3], [3, 0]].each do |a, b|
        side = [corners[a], corners[b], top[b], top[a]]
        visual.entities.add_face(side).material = blue_mat
      end
    end

  end
end
