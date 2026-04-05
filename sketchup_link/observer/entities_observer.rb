# frozen_string_literal: true

module SketchupLink
  module Observer
    class EntitiesObserver < Sketchup::EntitiesObserver
      def initialize(dispatcher)
        @dispatcher = dispatcher
      end

      def onElementAdded(entities, entity)
        @dispatcher.on_entity_added(entity)
      end

      def onElementModified(entities, entity)
        @dispatcher.on_entity_modified(entity)
      end

      def onElementRemoved(entities, entity_id)
        # entity_id is the integer persistent_id — entity itself is already deleted
        @dispatcher.on_entity_removed(entity_id)
      end
    end
  end
end
