# install_sketchup.ps1 - First-logon SketchUp installer for dockurr/windows VM
#
# Runs once on first user logon via startup folder (deployed by oem/install.bat).
# Orchestrates: SketchUp silent install -> crack -> plugin deployment -> self-removal.
#
# Shared folder (from host ./shared) is expected at:
#   C:\Users\Docker\Desktop\Shared
#
# SketchUp installer and crack files are in:
#   C:\Users\Docker\Desktop\Shared\installers\SketchUp2025\
#
# The SketchUp Link plugin is expected at:
#   C:\Users\Docker\Desktop\Shared\sketchup-link-extracted\

$logFile = "$env:TEMP\install_sketchup.log"
$sharedRoot = "$env:USERPROFILE\Desktop\Shared"

function Log {
    param([string]$msg)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp - $msg" | Out-File -FilePath $logFile -Append
    Write-Host $msg
}

Log "============================================================"
Log "SketchUp installation started"
Log "============================================================"

# ---------------------------------------------------------------------------
# Step 0: Wait for shared folder to become available (with retry)
# ---------------------------------------------------------------------------
$maxWait = 180
$waited = 0
$installerPath = "$sharedRoot\installers\SketchUp2025\Setup\SketchUpFull-2025-0-571-242.exe"
$pluginSrc = "$sharedRoot\sketchup-link-extracted"
$suInstallDir = "C:\Program Files\SketchUp\SketchUp 2025"
$layOutDir = "C:\Program Files\SketchUp\SketchUp 2025\LayOut"
$pluginsDir = "$env:APPDATA\SketchUp\SketchUp 2025\SketchUp\Plugins"

Log "Waiting for shared folder (max ${maxWait}s)..."
while (-not (Test-Path $installerPath)) {
    Start-Sleep -Seconds 5
    $waited += 5
    if ($waited -ge $maxWait) {
        Log "ERROR: Shared folder not available after ${maxWait}s."
        Log "Expected installer at: $installerPath"

        # Fallback: list what's available in shared root
        if (Test-Path $sharedRoot) {
            Log "Contents of shared root:"
            Get-ChildItem $sharedRoot -Depth 2 -Name 2>&1 | ForEach-Object { Log "  $_" }
        } else {
            Log "Shared root does not exist: $sharedRoot"
            Log "Network drives:"
            Get-PSDrive -PSProvider FileSystem | ForEach-Object { Log "  $($_.Name): $($_.Root)" }
        }
        exit 1
    }
    if ($waited % 30 -eq 0) {
        Log "Still waiting... (${waited}s)"
    }
}
Log "Shared folder ready after ${waited}s"

# ---------------------------------------------------------------------------
# Step 1: Install SketchUp silently (skip if already installed)
# ---------------------------------------------------------------------------
if (Test-Path "$suInstallDir\SketchUp\SketchUp.exe") {
    Log "SketchUp already installed at $suInstallDir - skipping installation"
} else {
    Log "Installing SketchUp 2025 silently..."
    Log "  Installer: $installerPath"

    if (-not (Test-Path $installerPath)) {
        Log "FATAL: Installer not found at $installerPath"
        exit 2
    }

    # manual testing has show /passive works, /silent does not
    $proc = Start-Process -FilePath $installerPath -ArgumentList "/passive" -Wait -NoNewWindow -PassThru
    Log "SketchUp installer exit code: $($proc.ExitCode)"

    if ($proc.ExitCode -ne 0) {
        Log "WARNING: SketchUp installer returned non-zero exit code"

        # Check if installed despite non-zero exit
        if (-not (Test-Path "$suInstallDir\SketchUp\SketchUp.exe")) {
            Log "ERROR: SketchUp.exe not found at $suInstallDir after installation"
            exit 2
        }
        Log "SketchUp.exe found despite non-zero exit - continuing"
    }
}

# ---------------------------------------------------------------------------
# Step 2: Apply crack (always re-apply to ensure latest)
# ---------------------------------------------------------------------------
$crackDir = "$sharedRoot\installers\SketchUp2025\Crack\SketchUp 2025"

Log "Applying crack files..."

# Kill any running instances first (might be auto-started after install)
Stop-Process -Name "SketchUp" -Force -ErrorAction SilentlyContinue
Stop-Process -Name "LayOut" -Force -ErrorAction SilentlyContinue

if (Test-Path "$crackDir\SketchUp\SketchUp.exe") {
    Copy-Item "$crackDir\SketchUp\SketchUp.exe" "$suInstallDir\SketchUp\" -Force
    Log "  Crack applied: SketchUp.exe -> $suInstallDir\SketchUp"
} else {
    Log "  WARNING: Cracked SketchUp.exe not found at $crackDir\SketchUp\SketchUp.exe"
    Log "  Contents of ${crackDir}:"
    Get-ChildItem "$crackDir" -Recurse -Name 2>&1 | ForEach-Object { Log "    $_" }
}

if (Test-Path "$crackDir\LayOut\LayOut.exe") {
    Copy-Item "$crackDir\LayOut\LayOut.exe" "$layOutDir\" -Force
    Log "  Crack applied: LayOut.exe -> $layOutDir"
} else {
    Log "  WARNING: Cracked LayOut.exe not found at $crackDir\LayOut\LayOut.exe"
}

# ---------------------------------------------------------------------------
# Step 3: Install SketchUp Link plugin
# ---------------------------------------------------------------------------
Log "Installing SketchUp Link plugin..."
Log "  Plugin source: $pluginSrc"
Log "  Plugins dir: $pluginsDir"

if (Test-Path "$pluginSrc\sketchup_link.rb") {
    # SketchUp auto-loads Plugins\*.rb at startup. Extensions\ copies do not auto-load, so remove any stale one.
    $legacyExtDir = "$env:APPDATA\SketchUp\SketchUp 2025\SketchUp\Extensions"
    foreach ($stale in @("$legacyExtDir\sketchup_link", "$legacyExtDir\sketchup_link.rb")) {
        if (Test-Path $stale) {
            Remove-Item $stale -Recurse -Force -ErrorAction Stop
            Log "  Removed stale Extensions copy $stale"
        }
    }

    New-Item -ItemType Directory -Force -Path "$pluginsDir" | Out-Null

    # Clean install: remove the whole previous plugin tree (stale nested folders caused partial copies)
    $pluginTree = "$pluginsDir\sketchup_link"
    if (Test-Path $pluginTree) {
        Remove-Item $pluginTree -Recurse -Force -ErrorAction Stop
        Log "  Removed old plugin directory $pluginTree"
    }
    $pluginEntry = "$pluginsDir\sketchup_link.rb"
    if (Test-Path $pluginEntry) {
        Remove-Item $pluginEntry -Force -ErrorAction Stop
        Log "  Removed old entry file $pluginEntry"
    }

    # Copy the plugin tree (sketchup_link\ with observer\ and serializer\) and the entry file
    try {
        Copy-Item -Path "$pluginSrc\sketchup_link" -Destination "$pluginsDir\" -Recurse -Force -ErrorAction Stop
        Copy-Item -Path "$pluginSrc\sketchup_link.rb" -Destination "$pluginsDir\" -Force -ErrorAction Stop
    } catch {
        Log "  ERROR: Plugin copy failed: $($_.Exception.Message)"
        throw
    }

    # Verify every source file exists in the installed tree, including nested folders
    $srcRoot = "$pluginSrc\sketchup_link"
    $srcFiles = @(Get-ChildItem $srcRoot -Recurse -File | ForEach-Object { $_.FullName.Substring($srcRoot.Length) })
    $missing = @($srcFiles | Where-Object { -not (Test-Path "$pluginTree$_") })
    if ((Test-Path $pluginEntry) -and ($missing.Count -eq 0)) {
        Log "  Plugin installed and verified: $($srcFiles.Count) files in sketchup_link\ plus entry file"
    } else {
        Log "  ERROR: Plugin install incomplete. Missing: $($missing -join ', ')"
        throw "Plugin install incomplete"
    }
} else {
    Log "  WARNING: Plugin entry file not found at $pluginSrc\sketchup_link.rb"
    if (Test-Path $pluginSrc) {
        Log "  Contents of plugin source directory:"
        Get-ChildItem $pluginSrc -Name 2>&1 | ForEach-Object { Log "    $_" }
    } else {
        Log "  Plugin source directory does not exist"
        Log "  Expected at: $pluginSrc"
        Log "  Contents of shared root:"
        Get-ChildItem $sharedRoot -Name 2>&1 | ForEach-Object { Log "    $_" }
    }
}

# ---------------------------------------------------------------------------
# Step 4: Suppress EULA on first launch
# ---------------------------------------------------------------------------
$prefsDir = "$env:LOCALAPPDATA\SketchUp\SketchUp 2025\SketchUp"
$prefsFile = "$prefsDir\PrivatePreferences.json"

Log "Suppressing SketchUp EULA on first launch..."

$prefs = @{
    "This Computer Only" = @{
        "Application" = @{
            "RunCounterSU" = 0
        }
        "Common" = @{
            "AcceptedTerms" = $true
        }
    }
}

New-Item -ItemType Directory -Force -Path $prefsDir | Out-Null
# BOM-less UTF-8: SketchUp discards PrivatePreferences.json if it starts with a BOM (PS 5.1 Out-File -Encoding UTF8 adds one), which brings the Trimble terms screen back
[System.IO.File]::WriteAllText($prefsFile, ($prefs | ConvertTo-Json -Depth 10), (New-Object System.Text.UTF8Encoding $false))
Log "  EULA suppressed"

# ---------------------------------------------------------------------------
# Step 5: Deploy auto-start scripts
# ---------------------------------------------------------------------------
$startupPath = "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp"

# Remove old installer scripts first
Remove-Item "$startupPath\install_sketchup.vbs" -Force -ErrorAction SilentlyContinue
Remove-Item "$startupPath\install_sketchup.ps1" -Force -ErrorAction SilentlyContinue

# Deploy launch_sketchup.vbs (hidden PowerShell launcher)
$vbsContent = @'
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "powershell.exe -ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File C:\OEM\launch_sketchup.ps1", 0, False
'@
$vbsContent | Out-File -FilePath "$startupPath\launch_sketchup.vbs" -Encoding ASCII -Force
Log "  Deployed launch_sketchup.vbs to startup folder"

# Deploy launch_sketchup.ps1 (auto-start worker)
$ps1Src = "C:\OEM\launch_sketchup.ps1"
if (Test-Path $ps1Src) {
    Log "  launch_sketchup.ps1 already at $ps1Src"
} else {
    Log "  WARNING: launch_sketchup.ps1 not found at $ps1Src - will be deployed from shared folder"
}

Log "Auto-start scripts deployed"
Log "  SketchUp will launch automatically on next Windows login"

# ---------------------------------------------------------------------------
# Step 6: Launch SketchUp immediately for first-boot
# ---------------------------------------------------------------------------
Log "Launching SketchUp now for first boot..."

# Enhanced PrivatePreferences.json with all suppression keys
$prefs = @{
    "This Computer Only" = @{
        "Application" = @{
            "RunCounterSU" = 0
            "ShowWelcomeScreen" = $false
        }
        "Common" = @{
            "AcceptedTerms" = $true
            "LicenseAgreed" = $true
        }
    }
}
$prefsDir2 = "$env:LOCALAPPDATA\SketchUp\SketchUp 2025\SketchUp"
$prefsFile2 = "$prefsDir2\PrivatePreferences.json"
New-Item -ItemType Directory -Force -Path $prefsDir2 | Out-Null
[System.IO.File]::WriteAllText($prefsFile2, ($prefs | ConvertTo-Json -Depth 10), (New-Object System.Text.UTF8Encoding $false))
Log "  Enhanced PrivatePreferences.json with all suppression keys"

# Hand off to the launcher: it kills stale processes, applies prefs, launches
# SketchUp, dismisses the Welcome promo, and verifies the plugin endpoint.
$launcher = "C:\OEM\launch_sketchup.ps1"
if (Test-Path $launcher) {
    Log "  Starting launch_sketchup.ps1 (launch + promo dismissal + plugin check)..."
    Start-Process -FilePath "powershell.exe" -ArgumentList "-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File $launcher" -WindowStyle Hidden
} else {
    Log "  WARNING: launch_sketchup.ps1 not found at $launcher - SketchUp not started"
}

# ---------------------------------------------------------------------------
# Step 6: Enable OpenSSH server (host command channel)
# Runs last and non-fatally, so an SSH problem never blocks the SketchUp install.
# ---------------------------------------------------------------------------
$sshStep = "C:\OEM\enable_ssh.ps1"
if (Test-Path $sshStep) {
    try {
        Log "Enabling OpenSSH server via enable_ssh.ps1..."
        & powershell.exe -ExecutionPolicy Bypass -NoProfile -File $sshStep
        Log "  enable_ssh.ps1 finished"
    } catch {
        Log "  WARNING: enable_ssh.ps1 failed: $($_.Exception.Message)"
    }
} else {
    Log "  WARNING: enable_ssh.ps1 not found at $sshStep - SSH not enabled"
}

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
Log "============================================================"
Log "SketchUp installation complete"
Log "  Log file: $logFile"
Log "  SketchUp: $suInstallDir\SketchUp.exe"
Log "  LayOut:   $layOutDir\LayOut.exe"
Log "  Plugin:   $pluginsDir"
Log "============================================================"
Log "  Shared log: $sharedRoot\install_sketchup.log"
Log "============================================================"

# Copy log to shared directory for host-side access
Copy-Item $logFile "$sharedRoot\install_sketchup.log" -Force -ErrorAction SilentlyContinue
if (Test-Path "$sharedRoot\install_sketchup.log") {
    Log "Log copied to shared directory for host access"
} else {
    Log "WARNING: Failed to copy log to shared directory"
}
