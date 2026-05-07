# frozen_string_literal: true

module SketchupLink
  module Observer
    class AppObserver < Sketchup::AppObserver
      def initialize(plugin)
        @plugin = plugin
        # Attach to whatever model is already open when the extension loads.
        reattach_model_observers(Sketchup.active_model) if Sketchup.active_model
      end

      def onNewModel(model)
        reattach_model_observers(model)
        SketchupLink.log(:info, 'New model created', guid: model.guid)
        @plugin.event_dispatcher.on_model_open(model)
      end

      def onOpenModel(model)
        reattach_model_observers(model)
        SketchupLink.log(:info, 'Model opened', path: model.path, guid: model.guid)
        @plugin.event_dispatcher.on_model_open(model)
      end

      def onQuit
        SketchupLink.log(:info, 'SketchUp quitting')
        @plugin.event_dispatcher.on_model_close(Sketchup.active_model)
        @plugin.stop
      end

      private

      def reattach_model_observers(model)
        return unless model

        @model_observer      ||= ModelObserver.new(@plugin.event_dispatcher)
        @entities_observer   ||= EntitiesObserver.new(@plugin.event_dispatcher)
        @selection_observer  ||= SelectionObserver.new(@plugin.event_dispatcher)
        @materials_observer  ||= MaterialsObserver.new(@plugin.event_dispatcher)
        @layers_observer     ||= LayersObserver.new(@plugin.event_dispatcher)

        model.add_observer(@model_observer) rescue SketchupLink.log(:warn, 'Failed to add model observer')
        model.entities.add_observer(@entities_observer) rescue SketchupLink.log(:warn, 'Failed to add entities observer')
        model.selection.add_observer(@selection_observer) rescue SketchupLink.log(:warn, 'Failed to add selection observer')
        model.materials.add_observer(@materials_observer) rescue SketchupLink.log(:warn, 'Failed to add materials observer')
        model.layers.add_observer(@layers_observer) rescue SketchupLink.log(:warn, 'Failed to add layers observer')
      end
    end
  end
end
