# frozen_string_literal: true

module SketchupLink
  VERSION        = '1.0.0'.freeze
  EXTENSION_ID   = 'com.sketchuplink'.freeze
  TIMER_INTERVAL = 0.05

  def self.default_socket_path
    tmp = ENV['TEMP'] || ENV['TMP'] || '/tmp'
    File.join(tmp, 'sketchup-link.sock')
  end

  DEFAULT_SOCKET_PATH = default_socket_path.freeze

  EVT_TRANSACTION_COMMIT = 'transaction.commit'.freeze
  EVT_TRANSACTION_UNDO   = 'transaction.undo'.freeze
  EVT_TRANSACTION_REDO   = 'transaction.redo'.freeze
  EVT_SELECTION_CHANGE   = 'selection.change'.freeze
  EVT_MATERIALS_CHANGE   = 'materials.change'.freeze
  EVT_LAYERS_CHANGE      = 'layers.change'.freeze
  EVT_MODEL_SAVE         = 'model.save'.freeze
  EVT_MODEL_OPEN         = 'model.open'.freeze
  EVT_MODEL_CLOSE        = 'model.close'.freeze

  ALL_EVENTS = [
    EVT_TRANSACTION_COMMIT, EVT_TRANSACTION_UNDO, EVT_TRANSACTION_REDO,
    EVT_SELECTION_CHANGE,   EVT_MATERIALS_CHANGE, EVT_LAYERS_CHANGE,
    EVT_MODEL_SAVE,         EVT_MODEL_OPEN,       EVT_MODEL_CLOSE
  ].freeze
end
