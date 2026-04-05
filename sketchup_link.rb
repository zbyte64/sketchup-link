# encoding: UTF-8
# frozen_string_literal: true

require 'sketchup'
require 'extensions'

module SketchupLink
  EXTENSION = SketchupExtension.new('SketchUp Link', File.join(__dir__, 'sketchup_link', 'main'))
  EXTENSION.description = 'Exposes the active SketchUp model over a Unix domain socket for live external access.'
  EXTENSION.version     = '1.0.0'
  EXTENSION.creator     = 'sketchup-link'

  Sketchup.register_extension(EXTENSION, true)
end
