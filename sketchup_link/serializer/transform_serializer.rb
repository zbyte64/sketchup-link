# frozen_string_literal: true

module SketchupLink
  module Serializer
    module TransformSerializer
      INCHES_TO_METERS = 0.0254

      # Converts a Geom::Transformation to a 16-element row-major flat array.
      # SketchUp's Transformation#to_a returns a column-major array, so we
      # transpose it. Translation components (indices 12, 13, 14 in row-major)
      # are converted from inches to meters.
      def self.serialize(transformation)
        # to_a returns column-major [m0,m1,m2,m3, m4,m5,m6,m7, ...]
        col_major = transformation.to_a

        # Transpose to row-major 4x4
        row_major = Array.new(16)
        4.times do |row|
          4.times do |col|
            row_major[row * 4 + col] = col_major[col * 4 + row]
          end
        end

        # Convert translation (last column in row-major: indices 3, 7, 11)
        row_major[3]  = row_major[3]  * INCHES_TO_METERS
        row_major[7]  = row_major[7]  * INCHES_TO_METERS
        row_major[11] = row_major[11] * INCHES_TO_METERS

        row_major
      end
    end
  end
end
