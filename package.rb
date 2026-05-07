#!/usr/bin/env ruby
# Packages sketchup-link as an RBZ (ZIP) file for SketchUp's Extension Manager.

require 'zip'
require 'fileutils'

EXT_DIR  = __dir__
DIST_DIR = File.join(__dir__, 'dist')

# Read version from canonical VERSION file at repo root
version = File.read(File.join(__dir__, 'VERSION')).strip

output = File.join(DIST_DIR, "sketchup-link-#{version}.rbz")
FileUtils.mkdir_p(DIST_DIR)
FileUtils.rm_f(output)

entries = []
ext_root = File.join(EXT_DIR, 'sketchup_link.rb')
entries << ext_root if File.file?(ext_root)
entries += Dir.glob(File.join(EXT_DIR, 'sketchup_link', '**', '*.rb')).reject { |f| File.directory?(f) }
Zip::File.open(output, create: true) do |zip|
  entries.each do |abs|
    rel = abs.sub("#{EXT_DIR}/", '')
    zip.add(rel, abs)
  end
end

puts "Created: #{output}"
