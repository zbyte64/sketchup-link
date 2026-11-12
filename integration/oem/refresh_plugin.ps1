# ---------------------------------------------------------------------------
# refresh_plugin.ps1 — re-deploy the SketchUp Link plugin into the guest.
#
# Repeatable counterpart to Step 3 of install_sketchup.ps1. The one-shot
# first-logon installer is gated by C:\OEM\.install_done, so it never re-copies
# the plugin on an already-installed guest. This script runs ONLY the copy +
# verify step, so a rebuilt extension can be pushed without reinstalling
# SketchUp, re-applying the crack, or touching the EULA.
#
# Trigger: run from the guest (desktop, or the web console's Run dialog):
#     powershell -ExecutionPolicy Bypass -NoProfile -File C:\OEM\refresh_plugin.ps1
#
# Source of truth is the shared folder the VM already mounts, so repackaging on
# the host (dist/*.rbz -> integration/shared/sketchup-link-extracted/) is all
# that is needed before running this.
# ---------------------------------------------------------------------------

$ErrorActionPreference = 'Stop'

$sharedRoot = "$env:USERPROFILE\Desktop\Shared"
$pluginSrc  = "$sharedRoot\sketchup-link-extracted"
$pluginsDir = "$env:APPDATA\SketchUp\SketchUp 2025\SketchUp\Plugins"
$logFile    = "C:\OEM\refresh_plugin.log"

function Log([string]$msg) {
    $line = "$(Get-Date -Format s) $msg"
    Write-Output $line
    Add-Content -Path $logFile -Value $line
}

Log "refresh_plugin: source=$pluginSrc dest=$pluginsDir"

if (-not (Test-Path "$pluginSrc\sketchup_link.rb")) {
    throw "No plugin entry at $pluginSrc\sketchup_link.rb — is the shared folder mounted?"
}

# Remove stale Extensions copies (they do not auto-load; see install_sketchup.ps1)
$legacyExtDir = "$env:APPDATA\SketchUp\SketchUp 2025\SketchUp\Extensions"
foreach ($stale in @("$legacyExtDir\sketchup_link", "$legacyExtDir\sketchup_link.rb")) {
    if (Test-Path $stale) {
        Remove-Item $stale -Recurse -Force
        Log "removed stale Extensions copy $stale"
    }
}

New-Item -ItemType Directory -Force -Path $pluginsDir | Out-Null

# Clean replace: stale nested folders previously caused partial copies
$pluginTree = "$pluginsDir\sketchup_link"
$pluginEntry = "$pluginsDir\sketchup_link.rb"
if (Test-Path $pluginTree)  { Remove-Item $pluginTree -Recurse -Force; Log "removed old $pluginTree" }
if (Test-Path $pluginEntry) { Remove-Item $pluginEntry -Force;         Log "removed old $pluginEntry" }

Copy-Item -Path "$pluginSrc\sketchup_link"    -Destination "$pluginsDir\" -Recurse -Force
Copy-Item -Path "$pluginSrc\sketchup_link.rb" -Destination "$pluginsDir\" -Force

# Verify every source file made it, including nested folders
$srcRoot  = "$pluginSrc\sketchup_link"
$srcFiles = @(Get-ChildItem $srcRoot -Recurse -File | ForEach-Object { $_.FullName.Substring($srcRoot.Length) })
$missing  = @($srcFiles | Where-Object { -not (Test-Path "$pluginTree$_") })

if ((Test-Path $pluginEntry) -and ($missing.Count -eq 0)) {
    Log "OK: $($srcFiles.Count) files deployed to $pluginTree"
    Log "Restart SketchUp so it loads the new Plugins\*.rb"
} else {
    throw "Plugin deploy incomplete. Missing: $($missing -join ', ')"
}
