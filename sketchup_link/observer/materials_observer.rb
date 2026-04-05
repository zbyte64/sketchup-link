# frozen_string_literal: true

module SketchupLink
  module Observer
    class MaterialsObserver < Sketchup::MaterialsObserver
      def initialize(dispatcher)
        @dispatcher = dispatcher
      end

      def onMaterialAdd(materials, material)
        @dispatcher.on_materials_change(materials.model)
      end

      def onMaterialRemove(materials, material)
        @dispatcher.on_materials_change(materials.model)
      end

      def onMaterialChange(materials, material)
        # Guard against accessing properties of a deleted material
        return if material.respond_to?(:deleted?) && material.deleted?

        @dispatcher.on_materials_change(materials.model)
      end

      def onMaterialRefChanged(materials, material)
        @dispatcher.on_materials_change(materials.model)
      end
    end
  end
end
