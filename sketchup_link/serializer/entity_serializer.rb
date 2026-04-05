# frozen_string_literal: true

module SketchupLink
  module Serializer
    module EntitySerializer
      INCHES_TO_METERS = 0.0254

      def self.serialize(entity)
        case entity
        when Sketchup::Face
          serialize_face(entity)
        when Sketchup::Edge
          serialize_edge(entity)
        when Sketchup::Group
          serialize_group(entity)
        when Sketchup::ComponentInstance
          serialize_instance(entity)
        when Sketchup::ComponentDefinition
          serialize_definition(entity)
        else
          { 'type' => entity.class.name, 'persistent_id' => persistent_id(entity) }
        end
      rescue StandardError => e
        { 'type' => 'Error', 'message' => e.message }
      end

      # ------------------------------------------------------------------
      # Face
      # ------------------------------------------------------------------
      def self.serialize_face(face)
        mesh = face.mesh(1)  # 1 = UVQFront — tessellates with UV coordinates

        vertices = (1..mesh.count_points).map do |i|
          pt = mesh.point_at(i)
          [pt.x * INCHES_TO_METERS, pt.y * INCHES_TO_METERS, pt.z * INCHES_TO_METERS]
        end

        uvs = (1..mesh.count_points).map do |i|
          uvq = mesh.uv_at(i, true)  # true = front face
          if uvq
            q = uvq.z.zero? ? 1.0 : uvq.z
            [uvq.x / q, uvq.y / q]
          else
            [0.0, 0.0]
          end
        end

        # polygon_at uses 1-based indices; negative = hidden edge → abs; convert to 0-based
        triangles = (1..mesh.count_polygons).map do |i|
          mesh.polygon_at(i).map { |idx| idx.abs - 1 }
        end

        outer_loop = face.outer_loop.vertices.map { |v| point_to_meters(v.position) }
        loops      = face.loops.map { |l| l.vertices.map { |v| point_to_meters(v.position) } }

        {
          'type'          => 'Face',
          'persistent_id' => persistent_id(face),
          'normal'        => face.normal.to_a,
          'area'          => face.area,
          'vertices'      => vertices,
          'triangles'     => triangles,
          'uvs'           => uvs,
          'outer_loop'    => outer_loop,
          'loops'         => loops,
          'material'      => face.material&.name,
          'back_material' => face.back_material&.name,
          'layer'         => face.layer&.name
        }
      end

      # ------------------------------------------------------------------
      # Edge
      # ------------------------------------------------------------------
      def self.serialize_edge(edge)
        {
          'type'          => 'Edge',
          'persistent_id' => persistent_id(edge),
          'vertices'      => edge.vertices.map { |v| point_to_meters(v.position) },
          'soft'          => edge.soft?,
          'smooth'        => edge.smooth?,
          'hidden'        => edge.hidden?,
          'layer'         => edge.layer&.name,
          'material'      => edge.material&.name
        }
      end

      # ------------------------------------------------------------------
      # Group
      # ------------------------------------------------------------------
      def self.serialize_group(group)
        {
          'type'           => 'Group',
          'persistent_id'  => persistent_id(group),
          'name'           => group.name,
          'transformation' => TransformSerializer.serialize(group.transformation),
          'layer'          => group.layer&.name,
          'entities'       => serialize_entities(group.entities)
        }
      end

      # ------------------------------------------------------------------
      # ComponentInstance
      # ------------------------------------------------------------------
      def self.serialize_instance(instance)
        {
          'type'            => 'ComponentInstance',
          'persistent_id'   => persistent_id(instance),
          'definition_name' => instance.definition.name,
          'transformation'  => TransformSerializer.serialize(instance.transformation),
          'layer'           => instance.layer&.name
        }
      end

      # ------------------------------------------------------------------
      # ComponentDefinition (used in model_serializer)
      # ------------------------------------------------------------------
      def self.serialize_definition(defn)
        {
          'name'               => defn.name,
          'guid'               => defn.guid,
          'num_instances'      => defn.count_instances,
          'num_used_instances' => defn.count_used_instances,
          'entities'           => serialize_entities(defn.entities)
        }
      end

      # ------------------------------------------------------------------
      # Material
      # ------------------------------------------------------------------
      def self.serialize_material(material)
        return nil unless material

        h = {
          'name'    => material.name,
          'color'   => color_to_hash(material.color),
          'opacity' => material.alpha
        }
        if material.texture
          tex = material.texture
          h['texture'] = {
            'filename' => tex.filename.to_s.gsub('\\', '/'),
            'width'    => tex.width  * INCHES_TO_METERS,
            'height'   => tex.height * INCHES_TO_METERS
          }
        end
        h
      end

      # ------------------------------------------------------------------
      # Layer
      # ------------------------------------------------------------------
      def self.serialize_layer(layer)
        {
          'name'       => layer.name,
          'visible'    => layer.visible?,
          'color'      => color_to_hash(layer.color),
          'line_width' => layer.line_width
        }
      rescue StandardError
        { 'name' => layer.name, 'visible' => layer.visible? }
      end

      # ------------------------------------------------------------------
      # Helpers
      # ------------------------------------------------------------------
      def self.serialize_entities(entities)
        entities.map { |e| serialize(e) }
      end

      def self.persistent_id(entity)
        entity.respond_to?(:persistent_id) ? entity.persistent_id : entity.entityID
      rescue StandardError
        nil
      end

      def self.point_to_meters(pt)
        [pt.x * INCHES_TO_METERS, pt.y * INCHES_TO_METERS, pt.z * INCHES_TO_METERS]
      end

      def self.color_to_hash(color)
        { 'r' => color.red, 'g' => color.green, 'b' => color.blue, 'a' => color.alpha }
      rescue StandardError
        { 'r' => 0, 'g' => 0, 'b' => 0, 'a' => 255 }
      end
    end
  end
end
