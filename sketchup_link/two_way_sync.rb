# frozen_string_literal: true

module SketchupLink
  # Two-way editing: Blender edits are written back into SketchUp only when this toggle is on. It is off by default,
  # and only an explicit true turns it on, so a missing or unreadable setting keeps SketchUp as the sole writer.
  module TwoWaySync
    module_function

    def enabled?(value)
      value == true
    end
  end
end
