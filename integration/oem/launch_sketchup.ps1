# launch_sketchup.ps1 - Auto-start SketchUp with plugin initialization.
#
# Runs from the All Users Startup folder on Windows login.
# Orchestrates: dialog suppression -> launch -> plugin verification.
#
# This script can also be called independently (e.g. from agent-rdp or
# wait-for-plugin.sh fallback) to re-launch SketchUp post-crash.
#
# Shared folder (from host ./shared) is expected at:
#   C:\Users\Docker\Desktop\Shared

# Shared folder path (defined first so the breadcrumb below can use it)
$sharedRoot = "$env:USERPROFILE\Desktop\Shared"

# Host-visible observability: the host can only read the shared folder, so every
# run leaves a breadcrumb and a copy of its log there. The breadcrumb is written
# with a bare Set-Content so it survives even if the rest of the script fails.
$guestLogDir = "$sharedRoot\guest_logs"
try {
    New-Item -ItemType Directory -Force -Path $guestLogDir | Out-Null
    Set-Content -Path "$guestLogDir\launch_started.txt" -Value ("started " + (Get-Date -Format s) + " user=" + $env:USERNAME)
} catch {
    # Shared folder not mounted yet; the local log below is the fallback.
}

$logFile = "$env:TEMP\launch_sketchup.log"

# SketchUp paths
$suInstallDir = "C:\Program Files\SketchUp\SketchUp 2025"
$suExe = "$suInstallDir\SketchUp\SketchUp.exe"
$prefsDir = "$env:LOCALAPPDATA\SketchUp\SketchUp 2025\SketchUp"
$prefsFile = "$prefsDir\PrivatePreferences.json"

# Plugin HTTP endpoint
$pluginHost = "127.0.0.1"
$pluginPort = 9876

# Timeouts
$sharedWaitMax = 30
$pluginPollMax = 120
$pluginPollInterval = 5

function Log {
    param([string]$msg)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$timestamp - $msg"
    $line | Out-File -FilePath $logFile -Append
    # Mirror to the shared folder so the host can read it. Never let mirroring fail the run.
    try { $line | Out-File -FilePath "$guestLogDir\launch_sketchup.log" -Append -Encoding UTF8 } catch { }
    Write-Host $msg
}

function Write-Status {
    param([string]$status, [string]$detail = "")
    $statusObj = @{
        "timestamp" = (Get-Date -Format "o")
        "status" = $status
        "detail" = $detail
    }
    $statusJson = $statusObj | ConvertTo-Json -Compress
    $statusJson | Out-File -FilePath "$env:TEMP\sketchup_status.json" -Encoding UTF8 -Force

    # Also write to shared folder if available
    $sharedStatus = "$sharedRoot\sketchup_status.json"
    try {
        $statusJson | Out-File -FilePath $sharedStatus -Encoding UTF8 -Force
    } catch {
        # Shared folder may not be available yet - that's fine
    }
}

function Wait-For-SharedFolder {
    Log "Waiting for shared folder (max ${sharedWaitMax}s)..."
    $waited = 0
    while (-not (Test-Path $sharedRoot)) {
        Start-Sleep -Seconds 2
        $waited += 2
        if ($waited -ge $sharedWaitMax) {
            Log "Shared folder not available after ${sharedWaitMax}s - continuing without it"
            return $false
        }
    }
    Log "Shared folder ready after ${waited}s"
    return $true
}

function Kill-Stale-Processes {
    Log "Killing any stale SketchUp processes..."
    Get-Process -Name "SketchUp" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Get-Process -Name "LayOut" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Log "Stale processes killed"
}

function Ensure-Preferences {
    Log "Ensuring dialog suppression in PrivatePreferences.json..."

    # Build the enhanced preferences including all known suppression keys
    $prefs = @{
        "This Computer Only" = @{
            "Application" = @{
                "RunCounterSU" = 0
                "ShowWelcomeScreen" = $false
                "ShowEULAOnStartup" = $false
                "SkipStartupDialog" = $true
            }
            "Common" = @{
                "AcceptedTerms" = $true
                "LicenseAgreed" = $true
            }
        }
    }

    # Overwrite rather than merge: this script owns the whole file (dialog suppression only).
    # The former merge branch always threw on PSCustomObject.ContainsKey and fell through to overwrite.

    # Ensure directory exists and write
    New-Item -ItemType Directory -Force -Path $prefsDir | Out-Null
    # BOM-less UTF-8: SketchUp discards PrivatePreferences.json if it starts with a BOM (see install_sketchup.ps1)
    [System.IO.File]::WriteAllText($prefsFile, ($prefs | ConvertTo-Json -Depth 10), (New-Object System.Text.UTF8Encoding $false))
    Log "  Preferences written to $prefsFile"
    # Debug: log preferences contents for troubleshooting
    if (Test-Path $prefsFile) {
        $prefsContent = Get-Content $prefsFile -Raw -Encoding UTF8
        Log "  Preferences content: $prefsContent"
    }
}
function Close-BingPopups {
    Log "Waiting for potential Bing/Edge popups to appear..."
    Start-Sleep -Seconds 20

    Log "Closing Bing/Edge popups..."
    # Kill Edge WebView2 processes (used by Widgets, Search, Bing popups)
    Get-Process -Name "msedgewebview2" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Get-Process -Name "msedge" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Get-Process -Name "Widgets" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Get-Process -Name "SearchHost" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

    # Fallback: use taskkill for thorough cleanup
    & taskkill /F /IM msedgewebview2.exe /T 2>$null
    & taskkill /F /IM msedge.exe /T 2>$null
    & taskkill /F /IM Widgets.exe /T 2>$null
    & taskkill /F /IM SearchHost.exe /T 2>$null

    Start-Sleep -Seconds 2
    Log "Bing/Edge popups handled"
}


# Dismisses the per-launch "Welcome to SketchUp" promo. It blocks extension
# loading and is NOT persisted to any prefs file (verified: relaunch shows it
# again). Only the promo's own buttons are clicked; Sign In / Add Classic
# License are never touched.
#
# Flow observed on the guest (1706x960): "Start modeling" switches the same
# dialog to a Home view with templates; choosing "Simple - Inches" closes it
# and opens a model, which lets the extension load.
#
# UIA cannot see the promo's web content: the CommonWebDialog exposes only an
# empty "Chrome Legacy Window" pane, even with SPI_SETSCREENREADER and
# WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--force-renderer-accessibility.
# So buttons are clicked at fixed fractions of the dialog's bounding rect.
# Dialog is fixed-size on this VM.
function Get-PromoWindow {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    foreach ($w in $root.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)) {
        $n = $w.Current.Name
        if ($w.Current.ClassName -eq "CommonWebDialog" -and ($n -eq "SketchUp" -or $n -eq "Welcome to SketchUp")) { return $w }
    }
    return $null
}

function Dismiss-WelcomePromo {
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class WinApi {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
}
"@
    [WinApi]::SetProcessDPIAware() | Out-Null
    $deadline = (Get-Date).AddSeconds(90)
    $seenPromo = $false
    $stage = 0
    while ((Get-Date) -lt $deadline) {
        $win = Get-PromoWindow
        if (-not $win) {
            if ($seenPromo) {
                Log "Welcome promo dismissed (stage $stage)"
                return $true
            }
            Start-Sleep -Seconds 2
            continue
        }
        $seenPromo = $true
        $hwnd = [IntPtr]$win.Current.NativeWindowHandle
        [WinApi]::ShowWindow($hwnd, 9) | Out-Null
        [WinApi]::SetForegroundWindow($hwnd) | Out-Null
        Start-Sleep -Seconds 2
        $r = $win.Current.BoundingRectangle
        if ($r.Width -gt 0 -and $r.Height -gt 0) {
            if ($stage -eq 0) { $fx = 0.8697; $fy = 0.9446; $label = "Start modeling" }
            else { $fx = 0.2850; $fy = 0.2730; $label = "Simple Inches template" }
            $x = [int]($r.Left + $r.Width * $fx)
            $y = [int]($r.Top + $r.Height * $fy)
            [WinApi]::SetCursorPos($x, $y) | Out-Null
            [WinApi]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
            [WinApi]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
            Log "Clicked promo '$label' at ($x,$y)"
            $stage = 1
            Start-Sleep -Seconds 3
        }
        Start-Sleep -Seconds 2
    }
    Log "Welcome promo not dismissed within 90s"
    return $false
}

function Start-SketchUp {
    if (-not (Test-Path $suExe)) {
        Log "ERROR: SketchUp.exe not found at $suExe"
        Write-Status -status "error" -detail "SketchUp.exe not found at $suExe"
        return $false
    }

    # Check if already running
    $existing = Get-Process -Name "SketchUp" -ErrorAction SilentlyContinue
    if ($existing) {
        Log "SketchUp already running (PID: $($existing.Id)) - skipping launch"
        return $true
    }

    Log "Launching SketchUp (minimized)..."
    try {
        $proc = Start-Process -FilePath $suExe -WindowStyle Minimized -PassThru
        Log "  Launched with PID: $($proc.Id)"
        return $true
    } catch {
        Log "ERROR: Failed to launch SketchUp: $_"
        Write-Status -status "error" -detail "Launch failed: $_"
        return $false
    }
}

function Wait-For-Plugin {
    Log "Waiting for plugin HTTP endpoint at http://${pluginHost}:${pluginPort}/status..."
    Log "  Timeout: ${pluginPollMax}s, Poll interval: ${pluginPollInterval}s"

    $startTime = Get-Date
    while ($true) {
        $elapsed = [int]((Get-Date) - $startTime).TotalSeconds

        try {
            $response = Invoke-WebRequest -Uri "http://${pluginHost}:${pluginPort}/status" -Method GET -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
            if ($response.StatusCode -eq 200) {
                Log "Plugin READY after ${elapsed}s (HTTP $($response.StatusCode))"
                Write-Status -status "ready" -detail "Plugin ready after ${elapsed}s"
                return $true
            }
        } catch {
            # Not responding yet - that's expected during startup
        }

        if ($elapsed -ge $pluginPollMax) {
            Log "TIMEOUT: Plugin not responding after ${pluginPollMax}s"
            Write-Status -status "timeout" -detail "Plugin not responding after ${pluginPollMax}s"
            return $false
        }

        Start-Sleep -Seconds $pluginPollInterval
    }
}

# ============================================================================
# Main
# ============================================================================
Log "============================================================"
Log "SketchUp auto-start launched"
Log "============================================================"

Write-Status -status "starting" -detail "Auto-start script launched"

# Step 1: Wait for shared folder
$sharedReady = Wait-For-SharedFolder

# Step 2: Kill stale processes
Kill-Stale-Processes

# Step 3: Suppress dialogs
Ensure-Preferences

# Step 3.5: One-time SSH bootstrap for VMs built before enable_ssh.ps1 existed.
# Runs once (marker-guarded), is non-fatal, and leaves no marker on failure so the
# next logon retries. It can never block the SketchUp launch below.
$sshMarker = "C:\OEM\.ssh_bootstrap_done"
if (-not (Test-Path $sshMarker) -and (Test-Path "C:\OEM\enable_ssh.ps1")) {
    Log "SSH bootstrap: running enable_ssh.ps1 (one-time)"
    try {
        & powershell.exe -ExecutionPolicy Bypass -NoProfile -File "C:\OEM\enable_ssh.ps1"
        if ($LASTEXITCODE -eq 0) {
            Set-Content -Path $sshMarker -Value (Get-Date -Format s)
            Log "SSH bootstrap: done (marker written)"
        } else {
            Log "SSH bootstrap: enable_ssh.ps1 exited $LASTEXITCODE; will retry next logon"
        }
    } catch {
        Log "SSH bootstrap: failed ($($_.Exception.Message)); will retry next logon"
    }
}

# Step 4: Launch SketchUp
$launched = Start-SketchUp
if (-not $launched) {
    Log "============================================================"
    Log "Auto-start FAILED - SketchUp could not be launched"
    Log "============================================================"
    exit 1
}

# Step 4.5: Close any Bing/Edge popups that may cover SketchUp
Close-BingPopups
# Step 4.6: Dismiss the per-launch "Welcome to SketchUp" promo (blocks plugin load)
Dismiss-WelcomePromo | Out-Null


# Step 5: Wait for plugin
$pluginReady = Wait-For-Plugin

# Step 6: Write final status
if ($pluginReady) {
    Log "============================================================"
    Log "Auto-start COMPLETE - SketchUp running with plugin"
    Log "============================================================"
    Write-Status -status "running" -detail "SketchUp running with plugin initialized"
    exit 0
} else {
    Log "============================================================"
    Log "Auto-start partial - SketchUp launched but plugin not verified"
    Log "============================================================"
    Write-Status -status "partial" -detail "SketchUp launched but plugin not ready"
    exit 0
}
