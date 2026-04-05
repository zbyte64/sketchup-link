# frozen_string_literal: true

module SketchupLink
  module Serializer
    module ModelSerializer
      def self.serialize(model, entity_serializer = EntitySerializer)
        {
          'model_guid'            => model.guid,
          'title'                 => model.title,
          'path'                  => model.path,
          'entities'              => entity_serializer.serialize_entities(model.entities),
          'materials'             => serialize_materials(model.materials, entity_serializer),
          'layers'                => serialize_layers(model.layers, entity_serializer),
          'component_definitions' => serialize_definitions(model.definitions, entity_serializer)
        }
      end

      def self.serialize_materials(materials, entity_serializer)
        materials.map { |m| entity_serializer.serialize_material(m) }.compact
      end

      def self.serialize_layers(layers, entity_serializer)
        layers.map { |l| entity_serializer.serialize_layer(l) }
      end

      # Returns a Hash keyed by definition name (matching component_definition_as_dict).
      # Groups are backed by anonymous definitions — skip them.
      def self.serialize_definitions(definitions, entity_serializer)
        result = {}
        definitions.each do |defn|
          next if defn.group?

          result[defn.name] = entity_serializer.serialize_definition(defn)
        end
        result
      end
    end
  end
end
