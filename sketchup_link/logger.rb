# frozen_string_literal: true

require 'logger'

module SketchupLink
  @logger = nil
  @log_level_map = { DEBUG: Logger::DEBUG, INFO: Logger::INFO, WARN: Logger::WARN, ERROR: Logger::ERROR }.freeze

  def self.logger
    return @logger if @logger

    @logger = Logger.new(LOG_FILE, LOG_MAX_FILES, LOG_MAX_SIZE)
    @logger.level = @log_level_map[LOG_LEVEL] || Logger::INFO
    @logger.formatter = proc do |severity, datetime, _progname, msg|
      "#{datetime.utc.strftime('%Y-%m-%dT%H:%M:%S.%3NZ')} [#{severity}] #{msg}\n"
    end
    @logger
  end

  def self.log(level, msg, context = {})
    ctx = context.empty? ? '' : " #{context.map { |k, v| "#{k}=#{v}" }.join(' ')}"
    logger.public_send(level.to_s.downcase, "#{msg}#{ctx}")
  end

  def self.log_error(msg, exception, context = {})
    ctx = context.empty? ? '' : " #{context.map { |k, v| "#{k}=#{v}" }.join(' ')}"
    logger.error("#{msg}: #{exception.class}: #{exception.message}#{ctx}")
    logger.error(exception.backtrace&.first(10)&.join("\n")) if exception.backtrace
  end
end
