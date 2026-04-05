# frozen_string_literal: true

module SketchupLink
  module Observer
    class SelectionObserver < Sketchup::SelectionObserver
      def initialize(dispatcher)
        @dispatcher = dispatcher
      end

      def onSelectionBulkChange(selection)
        @dispatcher.on_selection_change(selection.model)
      end

      def onSelectionCleared(selection)
        @dispatcher.on_selection_change(selection.model)
      end
    end
  end
end
