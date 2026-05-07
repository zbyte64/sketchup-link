# frozen_string_literal: true

module SketchupLink
  # Batches geometry changes across nested transactions and debounces
  # direct (un-transacted) entity edits. Dispatches selection, materials,
  # and layer events immediately.
  class EventDispatcher
    def initialize(subscription_manager)
      @sub_mgr            = subscription_manager
      @transaction_depth  = 0
      @batch              = new_batch
      @debounce_timer_id  = nil
    end

    # --- Transaction lifecycle (from ModelObserver) ---

    def on_transaction_start
      cancel_debounce
      SketchupLink.log(:debug, 'Transaction started', depth: @transaction_depth + 1)
      @transaction_depth += 1
    end

    def on_transaction_commit(model)
      @transaction_depth -= 1 if @transaction_depth > 0
      SketchupLink.log(:debug, 'Transaction committed', depth: @transaction_depth)
      if @transaction_depth == 0
        serialize_and_dispatch(EVT_TRANSACTION_COMMIT, model)
      end
    end

    def on_transaction_abort(model)
      @transaction_depth -= 1 if @transaction_depth > 0
      SketchupLink.log(:warn, 'Transaction aborted', depth: @transaction_depth)
      @batch = new_batch
    end

    def on_transaction_undo(model)
      SketchupLink.log(:info, 'Transaction undo')
      @transaction_depth = 0
      @batch = new_batch
      dispatch_simple(EVT_TRANSACTION_UNDO, model_meta(model))
    end

    def on_transaction_redo(model)
      SketchupLink.log(:info, 'Transaction redo')
      @transaction_depth = 0
      @batch = new_batch
      dispatch_simple(EVT_TRANSACTION_REDO, model_meta(model))
    end

    def on_model_save(model)
      SketchupLink.log(:info, 'Model saved')
      dispatch_simple(EVT_MODEL_SAVE, model_meta(model))
    end

    def on_model_open(model)
      SketchupLink.log(:info, 'Model opened/created')
      dispatch_simple(EVT_MODEL_OPEN, model_meta(model))
    end

    def on_model_close(model)
      SketchupLink.log(:info, 'Model closed')
      dispatch_simple(EVT_MODEL_CLOSE, model_meta(model))
    end

    # --- Entity changes (from EntitiesObserver) ---

    def on_entity_added(entity)
      add_to_batch(:added, entity)
      debounce_if_no_transaction
    end

    def on_entity_modified(entity)
      add_to_batch(:modified, entity)
      debounce_if_no_transaction
    end

    def on_entity_removed(entity_id)
      # entity already deleted — only the integer ID is available
      id = entity_id.is_a?(Integer) ? entity_id : entity_id.entityID rescue entity_id
      @batch[:removed] << id unless @batch[:removed].include?(id)
      debounce_if_no_transaction
    end

    # --- Immediate events ---

    def on_selection_change(model)
      serialized = model.selection.map { |e| Serializer::EntitySerializer.serialize(e) }
      dispatch_simple(EVT_SELECTION_CHANGE, model_meta(model).merge('selection' => serialized))
    end

    def on_materials_change(model)
      dispatch_simple(EVT_MATERIALS_CHANGE, model_meta(model))
    end

    def on_layers_change(model)
      dispatch_simple(EVT_LAYERS_CHANGE, model_meta(model))
    end

    private

    def new_batch
      { added: [], modified: [], removed: [] }
    end

    # Deduplicate by persistent_id; latest serialization wins for modified.
    def add_to_batch(key, entity)
      return unless entity.respond_to?(:valid?) && entity.valid?

      pid = persistent_id_of(entity)
      existing = @batch[key].find_index { |e| e['persistent_id'] == pid }
      serialized = Serializer::EntitySerializer.serialize(entity)
      if existing
        @batch[key][existing] = serialized
      else
        @batch[key] << serialized
      end
    end

    def persistent_id_of(entity)
      entity.respond_to?(:persistent_id) ? entity.persistent_id : entity.entityID
    rescue StandardError => e
      SketchupLink.log_error('persistent_id_of failed', e)
      nil
    end

    def debounce_if_no_transaction
      return if @transaction_depth > 0

      cancel_debounce
      model = Sketchup.active_model
      @debounce_timer_id = UI.start_timer(TIMER_INTERVAL) do
        @debounce_timer_id = nil
        serialize_and_dispatch(EVT_TRANSACTION_COMMIT, model)
      end
    end

    def cancel_debounce
      return unless @debounce_timer_id

      UI.stop_timer(@debounce_timer_id)
      @debounce_timer_id = nil
    end

    def serialize_and_dispatch(event, model)
      return if @batch[:added].empty? && @batch[:modified].empty? && @batch[:removed].empty?

      payload = model_meta(model).merge(
        'added'    => @batch[:added],
        'modified' => @batch[:modified],
        'removed'  => @batch[:removed]
      )
      SketchupLink.log(:info, 'Dispatching event', event: event, added: @batch[:added].size, modified: @batch[:modified].size, removed: @batch[:removed].size)
      @batch = new_batch
      @sub_mgr.dispatch(event, base_envelope(event, payload))
    end

    def dispatch_simple(event, data)
      SketchupLink.log(:info, 'Dispatching simple event', event: event)
      @sub_mgr.dispatch(event, base_envelope(event, data))
    end

    def base_envelope(event, data)
      {
        'event'     => event,
        'timestamp' => Time.now.to_f,
        'data'      => data
      }
    end

    def model_meta(model)
      return {} unless model

      { 'model_guid' => model.guid, 'title' => model.title }
    rescue StandardError => e
      SketchupLink.log_error('model_meta failed', e)
      {}
    end
  end
end
