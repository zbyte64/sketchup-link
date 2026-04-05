# frozen_string_literal: true

require_relative 'constants'
require_relative 'serializer/transform_serializer'
require_relative 'serializer/entity_serializer'
require_relative 'serializer/model_serializer'
require_relative 'observer/model_observer'
require_relative 'observer/entities_observer'
require_relative 'observer/selection_observer'
require_relative 'observer/materials_observer'
require_relative 'observer/layers_observer'
require_relative 'observer/app_observer'
require_relative 'subscription_manager'
require_relative 'event_dispatcher'
require_relative 'server'
require_relative 'plugin'

file_loaded(__FILE__)

SketchupLink::PLUGIN ||= SketchupLink::Plugin.new
