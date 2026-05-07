# frozen_string_literal: true

module SketchupLink
  # Remote control API for programmatic SketchUp model manipulation.
  #
  # All coordinate inputs use **meters** (matching the serialization convention).
  # Internal SketchUp units are inches — conversion is handled here.
  #
  # Usage (from server.rb route handler):
  #   status, response = RemoteControl.handle(sub_path, parsed_body)
  #   respond(client, status, JSON.generate(response))
  module RemoteControl
    METERS_TO_INCHES = 1.0 / 0.0254

    class << self
      # ------------------------------------------------------------------
      # Public entry point
      # ------------------------------------------------------------------

      # Routes a /control/* sub-path to the appropriate handler.
      # Returns [status_code, response_hash] suitable for JSON serialization.
      def handle(sub_path, params)
        SketchupLink.log(:info, 'Remote control action', sub_path: sub_path, params: params.inspect)
        case sub_path
        when 'camera'           then set_camera(params)
        when 'camera/zoom'      then zoom_camera(params)
        when 'layer'            then set_layer(params)
        when 'plugin'           then set_plugin(params)
        when 'texture'          then load_texture(params)
        when 'material'         then set_material(params)
        when 'material/delete'  then delete_material(params)
        when 'geometry/face'    then add_face(params)
        when 'geometry/edge'    then add_edge(params)
        when 'geometry/group'   then add_group(params)
        when 'geometry/component'  then add_component(params)
        when 'geometry/delete'  then delete_entity(params)
        when 'geometry/transform' then set_entity_transform(params)
        when 'model/clear'      then clear_model(params)
        when 'model/new'        then new_model(params)
        else
          [404, { 'error' => "unknown control path: #{sub_path}" }]
        end
      rescue => e
        SketchupLink.log_error('Remote control failed', e, sub_path: sub_path)
        [500, { 'error' => e.message, 'detail' => "#{e.class}: #{e.message}" }]
      end

      # ------------------------------------------------------------------
      # Camera
      # ------------------------------------------------------------------

      def set_camera(params)
        model = active_model
        return [400, { 'error' => 'no active model' }] unless model

        eye = params['eye']
        target = params['target']
        up = params['up']

        return [400, { 'error' => 'missing required field: eye' }] unless eye
        return [400, { 'error' => 'missing required field: target' }] unless target
        return [400, { 'error' => 'missing required field: up' }] unless up

        eye_pt    = Geom::Point3d.new(*meter_point_to_inches(eye))
        target_pt = Geom::Point3d.new(*meter_point_to_inches(target))
        up_vec    = Geom::Vector3d.new(*up)

        camera = Sketchup::Camera.new(eye_pt, target_pt, up_vec)

        fov = params['fov']
        camera.fov = fov.to_f if fov

        perspective = params['perspective']
        camera.perspective = perspective unless perspective.nil?

        model.active_view.camera = camera
        { 'ok' => true }
      end

      def zoom_camera(params)
        model = active_model
        return [400, { 'error' => 'no active model' }] unless model

        factor = params['factor']
        return [400, { 'error' => 'missing required field: factor' }] unless factor

        model.active_view.zoom(factor.to_f)
        { 'ok' => true }
      end

      # ------------------------------------------------------------------
      # Layers
      # ------------------------------------------------------------------

      def set_layer(params)
        model = active_model
        return [400, { 'error' => 'no active model' }] unless model

        name = params['name']
        return [400, { 'error' => 'missing required field: name' }] unless name

        layer = model.layers[name] || model.layers.add(name)

        visible = params['visible']
        layer.visible = visible unless visible.nil?

        { 'ok' => true }
      end

      # ------------------------------------------------------------------
      # Plugins
      # ------------------------------------------------------------------

      def set_plugin(params)
        name = params['name']
        return [400, { 'error' => 'missing required field: name' }] unless name

        ext = Sketchup.extensions[name]
        return [404, { 'error' => "extension not found: #{name}" }] unless ext

        enabled = params['enabled']
        return [400, { 'error' => 'missing required field: enabled' }] if enabled.nil?

        if enabled
          ext.check
        else
          ext.uncheck
        end

        { 'ok' => true, 'note' => 'extension changes may require a SketchUp restart' }
      end

      # ------------------------------------------------------------------
      # Textures / Materials
      # ------------------------------------------------------------------

      def load_texture(params)
        model = active_model
        return [400, { 'error' => 'no active model' }] unless model

        material_name = params['material_name']
        file_path = params['file_path']
        return [400, { 'error' => 'missing required field: material_name' }] unless material_name
        return [400, { 'error' => 'missing required field: file_path' }] unless file_path

        unless File.exist?(file_path)
          return [400, { 'error' => "texture file not found: #{file_path}" }]
        end

        material = model.materials[material_name] || model.materials.add(material_name)
        material.texture = file_path

        {
          'ok' => true,
          'material' => {
            'name'    => material_name,
            'texture' => file_path
          }
        }
      end

      def set_material(params)
        model = active_model
        return [400, { 'error' => 'no active model' }] unless model

        name = params['name']
        return [400, { 'error' => 'missing required field: name' }] unless name

        material = model.materials[name] || model.materials.add(name)

        color = params['color']
        if color
          r = color['r'].to_i.clamp(0, 255)
          g = color['g'].to_i.clamp(0, 255)
          b = color['b'].to_i.clamp(0, 255)
          material.color = Sketchup::Color.new(r, g, b)
        end

        opacity = params['opacity']
        material.alpha = opacity.to_f.clamp(0.0, 1.0) if opacity

        { 'ok' => true }
      end

      def delete_material(params)
        model = active_model
        return [400, { 'error' => 'no active model' }] unless model

        name = params['name']
        return [400, { 'error' => 'missing required field: name' }] unless name

        material = model.materials[name]
        return [404, { 'error' => "material not found: #{name}" }] unless material

        material.delete_self
        { 'ok' => true }
      end

      # ------------------------------------------------------------------
      # Geometry — Faces
      # ------------------------------------------------------------------

      def add_face(params)
        model = active_model
        return [400, { 'error' => 'no active model' }] unless model

        points = params['points']
        return [400, { 'error' => 'missing required field: points' }] unless points
        return [400, { 'error' => 'points must have at least 3 elements' }] unless points.length >= 3

        inch_points = points.map { |pt| meter_point_to_inches(pt) }

        run_transaction(model, 'Add Face') do
          face = model.entities.add_face(inch_points)

          material_name = params['material']
          if material_name && (mat = model.materials[material_name])
            face.material = mat
          end

          back_mat_name = params['back_material']
          if back_mat_name && (bmat = model.materials[back_mat_name])
            face.back_material = bmat
          end

          layer_name = params['layer']
          if layer_name && (lay = model.layers[layer_name])
            face.layer = lay
          end

          { 'ok' => true, 'persistent_id' => face.persistent_id }
        end
      end

      # ------------------------------------------------------------------
      # Geometry — Edges
      # ------------------------------------------------------------------

      def add_edge(params)
        model = active_model
        return [400, { 'error' => 'no active model' }] unless model

        start_pt = params['start']
        end_pt   = params['end']
        return [400, { 'error' => 'missing required field: start' }] unless start_pt
        return [400, { 'error' => 'missing required field: end' }] unless end_pt

        start_inch = meter_point_to_inches(start_pt)
        end_inch   = meter_point_to_inches(end_pt)

        run_transaction(model, 'Add Edge') do
          edge = model.entities.add_line(start_inch, end_inch)

          layer_name = params['layer']
          if layer_name && (lay = model.layers[layer_name])
            edge.layer = lay
          end

          { 'ok' => true, 'persistent_id' => edge.persistent_id }
        end
      end

      # ------------------------------------------------------------------
      # Geometry — Groups
      # ------------------------------------------------------------------

      def add_group(params)
        model = active_model
        return [400, { 'error' => 'no active model' }] unless model

        run_transaction(model, 'Add Group') do
          group = model.entities.add_group

          name = params['name']
          group.name = name if name

          layer_name = params['layer']
          if layer_name && (lay = model.layers[layer_name])
            group.layer = lay
          end

          transformation = params['transformation']
          if transformation
            group.transformation = row_major_to_transformation(transformation)
          end

          { 'ok' => true, 'persistent_id' => group.persistent_id }
        end
      end

      # ------------------------------------------------------------------
      # Geometry — Component Instances
      # ------------------------------------------------------------------

      def add_component(params)
        model = active_model
        return [400, { 'error' => 'no active model' }] unless model

        def_name = params['definition_name']
        return [400, { 'error' => 'missing required field: definition_name' }] unless def_name

        definition = model.definitions[def_name]
        return [404, { 'error' => "component definition not found: #{def_name}" }] unless definition

        run_transaction(model, 'Add Component') do
          transform = Geom::Transformation.new
          raw_transform = params['transformation']
          if raw_transform
            transform = row_major_to_transformation(raw_transform)
          end

          instance = model.entities.add_instance(definition, transform)

          layer_name = params['layer']
          if layer_name && (lay = model.layers[layer_name])
            instance.layer = lay
          end

          { 'ok' => true, 'persistent_id' => instance.persistent_id }
        end
      end

      # ------------------------------------------------------------------
      # Geometry — Delete Entity
      # ------------------------------------------------------------------

      def delete_entity(params)
        model = active_model
        return [400, { 'error' => 'no active model' }] unless model

        pid = params['persistent_id']
        return [400, { 'error' => 'missing required field: persistent_id' }] unless pid

        entity = find_entity_by_persistent_id(model, pid)
        return [404, { 'error' => "entity not found: pid=#{pid}" }] unless entity

        run_transaction(model, 'Delete Entity') do
          entity.erase!
          { 'ok' => true }
        end
      end

      # ------------------------------------------------------------------
      # Geometry — Set Entity Transform
      # ------------------------------------------------------------------

      def set_entity_transform(params)
        model = active_model
        return [400, { 'error' => 'no active model' }] unless model

        pid = params['persistent_id']
        return [400, { 'error' => 'missing required field: persistent_id' }] unless pid

        transformation = params['transformation']
        return [400, { 'error' => 'missing required field: transformation' }] unless transformation

        entity = find_entity_by_persistent_id(model, pid)
        return [404, { 'error' => "entity not found: pid=#{pid}" }] unless entity

        unless entity.respond_to?(:transformation=)
          return [400, { 'error' => "entity does not support transformation: pid=#{pid}" }]
        end

        run_transaction(model, 'Set Transform') do
          entity.transformation = row_major_to_transformation(transformation)
          { 'ok' => true }
        end
      end

      # ------------------------------------------------------------------
      # Model
      # ------------------------------------------------------------------

      def clear_model(_params)
        model = active_model
        return [400, { 'error' => 'no active model' }] unless model

        run_transaction(model, 'Clear Model') do
          model.entities.clear!
          { 'ok' => true }
        end
      end

      def new_model(_params)
        Sketchup.file_new
        { 'ok' => true }
      end

      # ------------------------------------------------------------------
      # Helpers
      # ------------------------------------------------------------------

      private

      def active_model
        Sketchup.active_model
      end

      # Converts a 3-element meter coordinate array to a Geom::Point3d in inches.
      def meter_point_to_inches(pt)
        Geom::Point3d.new(pt[0] * METERS_TO_INCHES, pt[1] * METERS_TO_INCHES, pt[2] * METERS_TO_INCHES)
      end

      # Converts a 16-element row-major flat array (meters for translation)
      # to a Geom::Transformation.
      #
      # Input is row-major (matching the serializer output format):
      #   indices 3, 7, 11 are translation components in meters.
      # We convert translation to inches, transpose to SketchUp's
      # column-major order, and construct the Transformation.
      def row_major_to_transformation(row_major)
        # Make a copy to avoid mutating the caller's array
        rm = row_major.dup

        # Convert translation from meters to inches (indices 3, 7, 11 in row-major)
        rm[3]  = rm[3]  * METERS_TO_INCHES
        rm[7]  = rm[7]  * METERS_TO_INCHES
        rm[11] = rm[11] * METERS_TO_INCHES

        # Transpose row-major → column-major
        col_major = Array.new(16)
        4.times do |row|
          4.times do |col|
            col_major[col * 4 + row] = rm[row * 4 + col]
          end
        end

        Geom::Transformation.new(col_major)
      end

      # Finds an entity by persistent_id across model.entities and all
      # component definitions. Returns the entity or nil.
      def find_entity_by_persistent_id(model, pid)
        model.entities.each { |e| return e if e.persistent_id == pid }
        model.definitions.each do |defn|
          defn.entities.each { |e| return e if e.persistent_id == pid }
        end
        nil
      end

      # Wraps geometry-modifying operations in a SketchUp transaction so the
      # existing observer/event pipeline is triggered.
      #
      # Returns [status_code, response_hash].
      # On success, returns the block's return value (must be a hash).
      # On error, aborts the transaction and returns [500, error_hash].
      def run_transaction(model, name)
        model.start_operation(name, true)
        result = yield
        model.commit_operation
        [200, result]
      rescue => e
        model.abort_operation rescue nil
        SketchupLink.log_error('Transaction failed', e, name: name)
        [500, { 'error' => e.message, 'detail' => "#{e.class}: #{e.message}" }]
      end
    end
  end
end
