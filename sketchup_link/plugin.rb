# frozen_string_literal: true

module SketchupLink
  class Plugin
    attr_reader :event_dispatcher, :subscription_manager

    def initialize
      socket_path = Sketchup.read_default(EXTENSION_ID, 'socket_path', DEFAULT_SOCKET_PATH)

      @subscription_manager = SubscriptionManager.new
      @event_dispatcher     = EventDispatcher.new(@subscription_manager)
      @server               = Server.new(@subscription_manager)

      @server.start(socket_path)
      Sketchup.add_observer(Observer::AppObserver.new(self))
      add_menu_items
    end

    def add_menu_items
      plugins_menu = UI.menu('Plugins')
      plugins_menu.add_item('SketchUp Link: Save Model JSON') do
        save_model_json
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


    def stop
      @server.stop
    end
  end
end
