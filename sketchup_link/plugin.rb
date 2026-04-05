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
    end

    def stop
      @server.stop
    end
  end
end
