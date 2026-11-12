# ---------------------------------------------------------------------------
# enable_ssh.ps1 — install and start the built-in Windows OpenSSH server.
#
# Provides a verifiable, scriptable command channel into the guest so the host
# can run PowerShell remotely (e.g. refresh_plugin.ps1) without GUI keystrokes.
#
# Idempotent: safe to run on every first-logon and on re-runs. Each step checks
# current state first and verifies the outcome, so a silent failure is reported.
#
# Auth: key-based. The host public key is read from the shared folder
# (authorized_keys), so no password is stored in the repo.
# ---------------------------------------------------------------------------

$ErrorActionPreference = 'Stop'

$logFile = 'C:\OEM\enable_ssh.log'
# Mirror to the shared folder so the host can read it (see launch_sketchup.ps1).
$guestLogDir = "$env:USERPROFILE\Desktop\Shared\guest_logs"
try { New-Item -ItemType Directory -Force -Path $guestLogDir | Out-Null } catch { }
function Log([string]$msg) {
    $line = "$(Get-Date -Format s) $msg"
    Write-Output $line
    Add-Content -Path $logFile -Value $line
    try { Add-Content -Path "$guestLogDir\enable_ssh.log" -Value $line } catch { }
}

Log 'enable_ssh: begin'

# 1. Install the OpenSSH server capability (no-op if already present)
$cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0'
if ($cap.State -ne 'Installed') {
    Log 'installing OpenSSH.Server capability'
    Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0' | Out-Null
} else {
    Log 'OpenSSH.Server already installed'
}

# 2. Start the service and make it start automatically
Set-Service -Name sshd -StartupType Automatic
if ((Get-Service sshd).Status -ne 'Running') {
    Start-Service sshd
}

# 3. Allow inbound SSH through the firewall (the firewall is normally disabled
#    by install.bat, but do not rely on that)
if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' `
        -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
    Log 'added firewall rule OpenSSH-Server-In-TCP'
}

# 4. Install the host's public key for key-based login (administrators use the
#    system-wide file, not the per-user one)
$hostKey = 'C:\Users\Docker\Desktop\Shared\ssh\host_key.pub'
$authKeys = 'C:\ProgramData\ssh\administrators_authorized_keys'
if (Test-Path $hostKey) {
    Copy-Item $hostKey $authKeys -Force
    icacls $authKeys /inheritance:r /grant 'Administrators:F' 'SYSTEM:F' | Out-Null
    Log "installed host public key to $authKeys"
} else {
    Log "WARNING: no host public key at $hostKey; key login will not work until one is provided"
}

# 5. Verify — report success only if the server is actually listening
Start-Sleep -Seconds 2
$listening = Get-NetTCPConnection -LocalPort 22 -State Listen -ErrorAction SilentlyContinue
if ((Get-Service sshd).Status -eq 'Running' -and $listening) {
    Log 'OK: sshd running and listening on port 22'
} else {
    throw 'enable_ssh: sshd is not listening on port 22'
}
