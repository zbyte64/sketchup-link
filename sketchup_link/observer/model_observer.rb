# frozen_string_literal: true

module SketchupLink
  module Observer
    class ModelObserver < Sketchup::ModelObserver
      def initialize(dispatcher)
        @dispatcher = dispatcher
      end

      def onTransactionStart(model)
        @dispatcher.on_transaction_start
      end

      def onTransactionCommit(model)
        @dispatcher.on_transaction_commit(model)
      end

      def onTransactionAbort(model)
        @dispatcher.on_transaction_abort(model)
      end

      def onTransactionUndo(model)
        @dispatcher.on_transaction_undo(model)
      end

      def onTransactionRedo(model)
        @dispatcher.on_transaction_redo(model)
      end

      def onAfterComponentSaveAs(model)
        @dispatcher.on_model_save(model)
      end

      # Fired after File > Save / File > Save As
      def onSaveModel(model)
        @dispatcher.on_model_save(model)
      end
    end
  end
end
