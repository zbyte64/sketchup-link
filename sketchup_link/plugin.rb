# frozen_string_literal: true

module SketchupLink
  class Plugin
    attr_reader :event_dispatcher, :subscription_manager

    def initialize
      socket_path = Sketchup.read_default(EXTENSION_ID, 'socket_path', DEFAULT_SOCKET_PATH)
      use_tcp     = Sketchup.read_default(EXTENSION_ID, 'use_tcp', DEFAULT_USE_TCP)
      tcp_port    = Sketchup.read_default(EXTENSION_ID, 'tcp_port', DEFAULT_TCP_PORT)

      @subscription_manager = SubscriptionManager.new
      @event_dispatcher     = EventDispatcher.new(@subscription_manager)
      @server               = Server.new(@subscription_manager)

      config = {
        mode: use_tcp ? :tcp : :unix,
        socket_path: socket_path,
        tcp_port: tcp_port
      }
      @server.start(config)
      Sketchup.add_observer(Observer::AppObserver.new(self))
      add_menu_items
    end

    def add_menu_items
      plugins_menu = UI.menu('Plugins')
      sub = plugins_menu.add_submenu('SketchUp Link')
      sub.add_item('Save Model JSON') do
        save_model_json
      end
      sub.add_item('Configure Connection...') do
        show_config_dialog
      end
      sub.add_item('Restart Server') do
        restart_server
      end
    end

    def save_model_json
      model = Sketchup.active_model
      return unless model

      path = '/shared/model_snapshot.json'
      json = JSON.generate(Serializer::ModelSerializer.serialize(model, Serializer::EntitySerializer))
      File.write(path, json)
      UI.messagebox("Model JSON saved to #{path}")
    rescue StandardError => e
      UI.messagebox("Failed to save model JSON: #{e.message}")
    end

    def show_config_dialog
      current_tcp    = Sketchup.read_default(EXTENSION_ID, 'use_tcp', DEFAULT_USE_TCP)
      current_socket = Sketchup.read_default(EXTENSION_ID, 'socket_path', DEFAULT_SOCKET_PATH)
      current_port   = Sketchup.read_default(EXTENSION_ID, 'tcp_port', DEFAULT_TCP_PORT)

      prompts  = ['Use TCP:', 'Socket Path:', 'TCP Port:']
      defaults = [current_tcp ? 'Yes' : 'No', current_socket, current_port.to_s]
      dropdown = ['Yes|No', '', '']

      results = UI.inputbox(prompts, defaults, dropdown, 'Configure SketchUp Link Connection')
      return unless results  # user cancelled

      use_tcp    = results[0] == 'Yes'
      socket_path = results[1].strip
      tcp_port   = results[2].to_i

      # Validate Unix socket path
      unless use_tcp
        if socket_path.empty?
          UI.messagebox('Socket path cannot be empty when using Unix socket mode.')
          return
        end
      end

      # Clamp TCP port to valid range
      tcp_port = tcp_port.clamp(1024, 65_535)

      save_and_apply_config(use_tcp, socket_path, tcp_port)
    end

    def save_and_apply_config(use_tcp, socket_path, tcp_port)
      Sketchup.write_default(EXTENSION_ID, 'use_tcp', use_tcp)
      Sketchup.write_default(EXTENSION_ID, 'socket_path', socket_path)
      Sketchup.write_default(EXTENSION_ID, 'tcp_port', tcp_port)

      @server.stop
      config = {
        mode: use_tcp ? :tcp : :unix,
        socket_path: socket_path,
        tcp_port: tcp_port
      }
      @server.start(config)

      mode_label = use_tcp ? 'TCP' : 'Unix Socket'
      UI.messagebox(
        "Connection settings saved and server restarted.\n\n" \
        "Mode: #{mode_label}\n" \
        "Socket: #{socket_path}\n" \
        "TCP Port: #{tcp_port}"
      )
    end

    def restart_server
      use_tcp    = Sketchup.read_default(EXTENSION_ID, 'use_tcp', DEFAULT_USE_TCP)
      socket_path = Sketchup.read_default(EXTENSION_ID, 'socket_path', DEFAULT_SOCKET_PATH)
      tcp_port   = Sketchup.read_default(EXTENSION_ID, 'tcp_port', DEFAULT_TCP_PORT)

      @server.stop
      config = {
        mode: use_tcp ? :tcp : :unix,
        socket_path: socket_path,
        tcp_port: tcp_port
      }
      @server.start(config)
      UI.messagebox('Server restarted with current settings.')
    end

    def stop
      @server.stop
    end
  end
end
