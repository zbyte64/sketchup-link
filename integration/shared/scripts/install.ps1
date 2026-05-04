$extDir = "C:\Users\Docker\AppData\Roaming\SketchUp\SketchUp 2025\SketchUp\Extensions"
$src = "\\tsclient\Shared\sketchup-link-extracted"

# Create directories
New-Item -ItemType Directory -Force -Path "$extDir\sketchup_link" | Out-Null

# Copy plugin files
Copy-Item "$src\sketchup_link\*" "$extDir\sketchup_link\" -Recurse -Force
Copy-Item "$src\sketchup_link.rb" "$extDir\" -Force

Write-Output "Plugin files installed successfully"
