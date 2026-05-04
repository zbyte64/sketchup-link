@echo off
set EXT=C:\Users\Docker\AppData\Roaming\SketchUp\SketchUp 2025\SketchUp\Extensions
set SRC=C:\Users\Docker\Desktop\Shared\sketchup-link-extracted
mkdir "%EXT%\sketchup_link" 2>nul
xcopy "%SRC%\sketchup_link" "%EXT%\sketchup_link" /E /I /Y /Q
copy "%SRC%\sketchup_link.rb" "%EXT%" /Y
echo Plugin installed successfully
