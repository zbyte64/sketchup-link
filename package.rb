#!/usr/bin/env ruby
# Packages sketchup-link as an RBZ (ZIP) file for SketchUp's Extension Manager.

require 'zip'
require 'fileutils'

EXT_DIR  = __dir__
DIST_DIR = File.join(__dir__, 'dist')

# Extract version from constants.rb
constants = File.read(File.join(EXT_DIR, 'sketchup_link/constants.rb'))
version   = constants[/VERSION\s*=\s*['"]([^'"]+)['"]/, 1] or abort('Could not parse VERSION')

output = File.join(DIST_DIR, "sketchup-link-#{version}.rbz")
FileUtils.mkdir_p(DIST_DIR)
FileUtils.rm_f(output)

entries = Dir.glob(File.join(EXT_DIR, '**', '*')).reject { |f| File.directory?(f) }

Zip::File.open(output, create: true) do |zip|
  entries.each do |abs|
    rel = abs.sub("#{EXT_DIR}/", '')
    zip.add(rel, abs)
  end
end

puts "Created: #{output}"
