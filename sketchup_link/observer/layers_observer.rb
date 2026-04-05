# frozen_string_literal: true

module SketchupLink
  module Observer
    class LayersObserver < Sketchup::LayersObserver
      def initialize(dispatcher)
        @dispatcher = dispatcher
      end

      def onLayerAdded(layers, layer)
        @dispatcher.on_layers_change(layers.model)
      end

      def onLayerChanged(layers, layer)
        @dispatcher.on_layers_change(layers.model)
      end

      def onLayerRemoved(layers, layer)
        @dispatcher.on_layers_change(layers.model)
      end
    end
  end
end
