# frozen_string_literal: true

module SketchupLink
  module Serializer
    module ModelSerializer
      def self.serialize(model, entity_serializer = EntitySerializer)
        {
          'model_guid'            => model.guid,
          'camera'                => serialize_camera(model.active_view.camera),
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
      def self.serialize_camera(camera)
        eye          = camera.eye
        target       = camera.target
        up           = camera.up
        perspective  = camera.perspective?
        fov          = camera.fov
        aspect_ratio = camera.aspect_ratio

        {
          'eye'          => [eye.x.to_f * EntitySerializer::INCHES_TO_METERS, eye.y.to_f * EntitySerializer::INCHES_TO_METERS, eye.z.to_f * EntitySerializer::INCHES_TO_METERS],
          'target'       => [target.x.to_f * EntitySerializer::INCHES_TO_METERS, target.y.to_f * EntitySerializer::INCHES_TO_METERS, target.z.to_f * EntitySerializer::INCHES_TO_METERS],
          'up'           => [up.x.to_f, up.y.to_f, up.z.to_f],
          'perspective'  => perspective,
          'fov'          => perspective ? fov.to_f : 0.0,
          'aspect_ratio' => aspect_ratio.is_a?(Numeric) ? aspect_ratio.to_f : false
        }
      rescue StandardError
        nil
      end
    end
  end
end
