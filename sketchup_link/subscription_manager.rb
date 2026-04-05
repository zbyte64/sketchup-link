# frozen_string_literal: true

require 'securerandom'
require 'json'

module SketchupLink
  class SubscriptionManager
    def initialize
      @subscriptions = {}  # uuid => { events: Array<String>, socket: UNIXSocket }
    end

    # Registers client_socket as a subscriber. Returns the subscription uuid.
    def subscribe(client_socket, events)
      id = SecureRandom.uuid
      @subscriptions[id] = { events: events, socket: client_socket }
      id
    end

    # Closes and removes the subscription by id.
    def unsubscribe(id)
      entry = @subscriptions.delete(id)
      return unless entry

      entry[:socket].close rescue nil
    end

    # Called by Server when a socket is removed (EOF / EPIPE / explicit close).
    def remove_by_socket(socket)
      @subscriptions.reject! { |_id, sub| sub[:socket].equal?(socket) }
    end

    # Pushes an event to all matching subscribers via their persistent sockets.
    # Dead sockets are pruned automatically.
    def dispatch(event, payload)
      line = JSON.generate(payload) + "\n"
      chunk = make_chunk(line)
      dead = []

      @subscriptions.each do |id, sub|
        next unless matches?(sub[:events], event)

        begin
          sub[:socket].write(chunk)
          sub[:socket].flush
        rescue Errno::EPIPE, IOError
          dead << id
        end
      end

      dead.each { |id| @subscriptions.delete(id) }
    end

    def status
      {
        'version'       => VERSION,
        'model'         => Sketchup.active_model&.title || '',
        'subscriptions' => @subscriptions.size
      }
    end

    private

    def matches?(subscribed_events, event)
      subscribed_events.include?('*') || subscribed_events.include?(event)
    end

    def make_chunk(data)
      "#{data.bytesize.to_s(16)}\r\n#{data}\r\n"
    end
  end
end
