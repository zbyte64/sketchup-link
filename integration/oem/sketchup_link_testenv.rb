# frozen_string_literal: true
#
# Test-VM only. Sets the sketchup-link transport to TCP so the host can reach
# the SketchUp plugin on 127.0.0.1:9876 (the product default stays Unix-first,
# DEFAULT_USE_TCP = false in sketchup_link/constants.rb).
#
# Why a loader and a restart: the plugin reads `use_tcp` when it constructs the
# server, so on a cold boot the preference must be written first and the server
# restarted once the plugin exists. Both steps are idempotent, so a reboot or a
# SketchUp restart reapplies the same state.
#
# Installed into SketchUp's Plugins folder by the OEM setup (see enable_ssh.ps1
# / launch_sketchup.ps1). Not shipped in the product .rbz.

require 'sketchup.rb'

module SketchupLinkTestEnv
  EXTENSION_ID = 'com.sketchuplink'
  TCP_PORT = 9876

  def self.apply
    Sketchup.write_default(EXTENSION_ID, 'use_tcp', true)
    Sketchup.write_default(EXTENSION_ID, 'tcp_port', TCP_PORT)

    # The plugin may not exist yet on a cold boot; retry briefly until it does.
    return retry_later if !defined?(SketchupLink::PLUGIN) || SketchupLink::PLUGIN.nil?

    server = SketchupLink::PLUGIN.instance_variable_get(:@server)
    return retry_later unless server

    # Only restart if the server is not already on TCP, so repeated loads are cheap.
    return if server.instance_variable_get(:@mode) == :tcp

    server.stop
    server.start({ mode: :tcp, socket_path: SketchupLink::DEFAULT_SOCKET_PATH, tcp_port: TCP_PORT })
  end

  def self.retry_later(attempts = 10)
    return if attempts <= 0

    UI.start_timer(1.0, false) do
      if defined?(SketchupLink::PLUGIN) && SketchupLink::PLUGIN
        apply
      else
        retry_later(attempts - 1)
      end
    end
  end
end

SketchupLinkTestEnv.apply
