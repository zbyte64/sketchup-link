#!/usr/bin/env bash
# sketchup-install.sh — Reliable, idempotent SketchUp + plugin installer.
#
# Orchestrates installation of SketchUp, crack, plugin, and EULA suppression
# inside the Windows VM. Uses win-exec.sh and win-check.sh for all
# operations.
#
# Usage:
#   sketchup-install.sh              # Full install (SketchUp + crack + plugin + EULA)
#   sketchup-install.sh --plugin-only  # Only install/reinstall the plugin
#   sketchup-install.sh --status       # Check install status, don't install

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIN_EXEC="$SCRIPT_DIR/win-exec.sh"
WIN_CHECK="$SCRIPT_DIR/win-check.sh"
WAIT_PLUGIN="$SCRIPT_DIR/wait-for-plugin.sh"
SHARED_DIR="$(cd "$SCRIPT_DIR/../shared" && pwd)"

PLUGIN_ONLY=false
STATUS_ONLY=false
AUTO_START=false
AUTO_START_REMOVE=false

# Windows-side paths (backslash)
SU_EXE='C:\Program Files\SketchUp\SketchUp 2025\SketchUp\SketchUp.exe'
PLUGIN_ENTRY='C:\Users\Docker\AppData\Roaming\SketchUp\SketchUp 2025\SketchUp\Extensions\sketchup_link.rb'
PLUGIN_DIR_WIN='C:\Users\Docker\AppData\Roaming\SketchUp\SketchUp 2025\SketchUp\Extensions\sketchup_link'
PLUGIN_SRC='C:\Users\Docker\Desktop\Shared\sketchup-link-extracted'
INSTALLER='C:\Users\Docker\Desktop\Shared\installers\SketchUp2025\Setup\SketchUpFull-2025-0-571-242.exe'
CRACK_DIR='C:\Users\Docker\Desktop\Shared\installers\SketchUp2025\Crack\SketchUp 2025'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { echo "[sketchup-install] $*"; }
die()  { log "FATAL: $*"; exit 1; }
pass() { log "PASS: $*"; }
warn() { log "WARNING: $*"; }

# ---------------------------------------------------------------------------
# Status check
# ---------------------------------------------------------------------------
check_status() {
    echo ""
    log "=== SketchUp Installation Status ==="
    echo ""

    local sketches_installed=false
    local plugin_installed=false
    local plugin_running=false

    # Check if SketchUp.exe exists
    if "$WIN_EXEC" --no-connect --timeout 30 \
        "cmd /c if exist \"${SU_EXE}\" (echo FOUND) else (echo NOTFOUND)" \
        ".check_su_$$.txt" 2>/dev/null; then
        local result
        result=$(cat "$SHARED_DIR/.check_su_$$.txt" 2>/dev/null || echo "")
        if echo "$result" | grep -q "FOUND"; then
            pass "SketchUp executable: INSTALLED"
            sketches_installed=true
        else
            log "  SketchUp executable: NOT INSTALLED"
        fi
    else
        log "  SketchUp executable: check failed (win-exec error)"
    fi
    rm -f "$SHARED_DIR/.check_su_$$.txt" "$SHARED_DIR/.check_su_$$.txt.exitcode" 2>/dev/null || true

    # Check if plugin entry file exists
    if "$WIN_EXEC" --no-connect --timeout 30 \
        "cmd /c if exist \"${PLUGIN_ENTRY}\" (echo FOUND) else (echo NOTFOUND)" \
        ".check_plugin_$$.txt" 2>/dev/null; then
        local result
        result=$(cat "$SHARED_DIR/.check_plugin_$$.txt" 2>/dev/null || echo "")
        if echo "$result" | grep -q "FOUND"; then
            pass "Plugin entry file: INSTALLED"
            plugin_installed=true
        else
            log "  Plugin entry file: NOT INSTALLED"
        fi
    else
        log "  Plugin entry file: check failed"
    fi
    rm -f "$SHARED_DIR/.check_plugin_$$.txt" "$SHARED_DIR/.check_plugin_$$.txt.exitcode" 2>/dev/null || true

    # Check if SketchUp process is running
    if "$WIN_EXEC" --no-connect --timeout 30 \
        "cmd /c tasklist /NH /FI \"IMAGENAME eq SketchUp.exe\" | findstr SketchUp" \
        ".check_proc_$$.txt" 2>/dev/null; then
        local result
        result=$(cat "$SHARED_DIR/.check_proc_$$.txt" 2>/dev/null || echo "")
        if echo "$result" | grep -qi "SketchUp"; then
            log "  SketchUp process: RUNNING"
            plugin_running=true
        fi
    else
        log "  SketchUp process: NOT RUNNING"
    fi
    rm -f "$SHARED_DIR/.check_proc_$$.txt" "$SHARED_DIR/.check_proc_$$.txt.exitcode" 2>/dev/null || true

    # Check plugin HTTP
    if curl -s --connect-timeout 5 --max-time 10 "http://127.0.0.1:9876/status" >/dev/null 2>&1; then
        pass "Plugin HTTP endpoint: RESPONDING"
        plugin_running=true
    else
        log "  Plugin HTTP endpoint: NOT RESPONDING"
    fi

    echo ""
    if [[ "$sketches_installed" == "true" && "$plugin_installed" == "true" && "$plugin_running" == "true" ]]; then
        pass "SketchUp is fully installed and running"
        return 0
    fi

    echo "  Status: INCOMPLETE"
    [[ "$sketches_installed" == "false" ]] && echo "    - SketchUp not installed"
    [[ "$plugin_installed" == "false" ]] && echo "    - Plugin not installed"
    [[ "$plugin_running" == "false" ]] && echo "    - Plugin not running"
    return 1
}

# ---------------------------------------------------------------------------
# Plugin install
# ---------------------------------------------------------------------------
install_plugin() {
    log "=== Installing SketchUp Link plugin ==="

    # Verify plugin source exists in shared folder
    local host_plugin_src="$SHARED_DIR/sketchup-link-extracted"
    if [[ ! -f "$host_plugin_src/sketchup_link.rb" ]]; then
        die "Plugin source not found at $host_plugin_src/sketchup_link.rb"
    fi

    # Create extensions directory and copy files
    log "Creating extensions directory..."
    "$WIN_EXEC" --timeout 30 \
        "cmd /c mkdir \"${PLUGIN_DIR_WIN}\" 2>nul && echo DONE" \
        ".plugin_mkdir_$$.txt" 2>/dev/null || true
    rm -f "$SHARED_DIR/.plugin_mkdir_$$.txt" "$SHARED_DIR/.plugin_mkdir_$$.txt.exitcode" 2>/dev/null || true

    # Copy plugin files from shared folder
    log "Copying plugin files to $PLUGIN_DIR_WIN..."
    "$WIN_EXEC" --timeout 60 \
        "cmd /c xcopy \"${PLUGIN_SRC}\\sketchup_link\" \"${PLUGIN_DIR_WIN}\" /E /I /Y /Q && copy \"${PLUGIN_SRC}\\sketchup_link.rb\" \"${PLUGIN_DIR_WIN}\\..\" /Y && echo COPY_DONE" \
        ".plugin_copy_$$.txt" 2>/dev/null || true

    local result
    result=$(cat "$SHARED_DIR/.plugin_copy_$$.txt" 2>/dev/null || echo "")
    rm -f "$SHARED_DIR/.plugin_copy_$$.txt" "$SHARED_DIR/.plugin_copy_$$.txt.exitcode" 2>/dev/null || true

    if echo "$result" | grep -q "COPY_DONE"; then
        pass "Plugin files copied successfully"
    else
        warn "Plugin copy output: $result"
        # Try PowerShell copy instead
        log "Retrying with PowerShell copy..."
        "$WIN_EXEC" --timeout 60 \
            "powershell -Command \"Copy-Item '${PLUGIN_SRC}\\sketchup_link\\*' '${PLUGIN_DIR_WIN}\\' -Recurse -Force; Copy-Item '${PLUGIN_SRC}\\sketchup_link.rb' '${PLUGIN_DIR_WIN}\\..' -Force; Write-Output COPY_DONE\"" \
            ".plugin_pscopy_$$.txt" 2>/dev/null || true
        local result2
        result2=$(cat "$SHARED_DIR/.plugin_pscopy_$$.txt" 2>/dev/null || echo "")
        rm -f "$SHARED_DIR/.plugin_pscopy_$$.txt" "$SHARED_DIR/.plugin_pscopy_$$.txt.exitcode" 2>/dev/null || true
        if echo "$result2" | grep -q "COPY_DONE"; then
            pass "Plugin files copied (PowerShell method)"
        else
            die "Plugin copy failed even with PowerShell"
        fi
    fi

    # Verify
    log "Verifying plugin installation..."
    if "$WIN_EXEC" --no-connect --timeout 30 \
        "cmd /c if exist \"${PLUGIN_ENTRY}\" (echo FOUND) else (echo NOTFOUND)" \
        ".plugin_verify_$$.txt" 2>/dev/null; then
        local verify_result
        verify_result=$(cat "$SHARED_DIR/.plugin_verify_$$.txt" 2>/dev/null || echo "")
        if echo "$verify_result" | grep -q "FOUND"; then
            pass "Plugin installation verified"
        else
            die "Plugin verification failed — entry file not found after copy"
        fi
    fi
    rm -f "$SHARED_DIR/.plugin_verify_$$.txt" "$SHARED_DIR/.plugin_verify_$$.txt.exitcode" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# SketchUp install
# ---------------------------------------------------------------------------
install_sketchup() {
    log "=== Installing SketchUp 2025 ==="

    # Check if already installed
    if "$WIN_EXEC" --no-connect --timeout 30 \
        "cmd /c if exist \"${SU_EXE}\" (echo FOUND) else (echo NOTFOUND)" \
        ".su_check_$$.txt" 2>/dev/null; then
        local result
        result=$(cat "$SHARED_DIR/.su_check_$$.txt" 2>/dev/null || echo "")
        rm -f "$SHARED_DIR/.su_check_$$.txt" "$SHARED_DIR/.su_check_$$.txt.exitcode" 2>/dev/null || true
        if echo "$result" | grep -q "FOUND"; then
            pass "SketchUp already installed, skipping"
            return 0
        fi
    fi
    rm -f "$SHARED_DIR/.su_check_$$.txt" "$SHARED_DIR/.su_check_$$.txt.exitcode" 2>/dev/null || true

    # Verify installer exists
    local host_installer="$SHARED_DIR/installers/SketchUp2025/Setup/SketchUpFull-2025-0-571-242.exe"
    if [[ ! -f "$host_installer" ]]; then
        die "SketchUp installer not found at $host_installer"
    fi
    log "Installer found: $host_installer ($(stat -c%s "$host_installer" 2>/dev/null || stat -f%z "$host_installer" 2>/dev/null) bytes)"

    # Verify installer is accessible from Windows side
    log "Checking installer access from Windows..."
    if "$WIN_EXEC" --no-connect --timeout 30 \
        "cmd /c if exist \"${INSTALLER}\" (echo FOUND) else (echo NOTFOUND)" \
        ".installer_check_$$.txt" 2>/dev/null; then
        local result
        result=$(cat "$SHARED_DIR/.installer_check_$$.txt" 2>/dev/null || echo "")
        rm -f "$SHARED_DIR/.installer_check_$$.txt" "$SHARED_DIR/.installer_check_$$.txt.exitcode" 2>/dev/null || true
        if ! echo "$result" | grep -q "FOUND"; then
            die "Installer not accessible from Windows shared folder"
        fi
    fi

    # Run installer
    log "Running SketchUp installer (this may take several minutes)..."
    log "  Installer: $INSTALLER"
    log "  Arguments: /passive"

    if "$WIN_EXEC" --timeout 1800 \
        "cmd /c \"${INSTALLER}\" /passive && echo INSTALL_DONE" \
        ".su_install_$$.txt" 2>/dev/null; then
        local result
        result=$(cat "$SHARED_DIR/.su_install_$$.txt" 2>/dev/null || echo "")
        rm -f "$SHARED_DIR/.su_install_$$.txt" "$SHARED_DIR/.su_install_$$.txt.exitcode" 2>/dev/null || true

        if echo "$result" | grep -q "INSTALL_DONE"; then
            pass "SketchUp installer completed"
        elif echo "$result" | grep -q "error\|ERROR\|Error"; then
            warn "Installer may have errors in output"
            echo "$result"
        else
            log "Installer output:"
            echo "$result"
        fi
    else
        warn "SketchUp installer returned non-zero exit"
        # Check if installed despite non-zero exit
        if "$WIN_EXEC" --no-connect --timeout 30 \
            "cmd /c if exist \"${SU_EXE}\" (echo FOUND) else (echo NOTFOUND)" \
            ".su_verify_$$.txt" 2>/dev/null; then
            local result
            result=$(cat "$SHARED_DIR/.su_verify_$$.txt" 2>/dev/null || echo "")
            rm -f "$SHARED_DIR/.su_verify_$$.txt" "$SHARED_DIR/.su_verify_$$.txt.exitcode" 2>/dev/null || true
            if echo "$result" | grep -q "FOUND"; then
                warn "SketchUp installed despite installer non-zero exit — continuing"
            else
                die "SketchUp installation failed"
            fi
        fi
    fi

    # Verify SketchUp installed
    sleep 5
    log "Verifying SketchUp installation..."
    if "$WIN_EXEC" --no-connect --timeout 30 \
        "cmd /c if exist \"${SU_EXE}\" (echo FOUND) else (echo NOTFOUND)" \
        ".su_final_verify_$$.txt" 2>/dev/null; then
        local result
        result=$(cat "$SHARED_DIR/.su_final_verify_$$.txt" 2>/dev/null || echo "")
        rm -f "$SHARED_DIR/.su_final_verify_$$.txt" "$SHARED_DIR/.su_final_verify_$$.txt.exitcode" 2>/dev/null || true
        if echo "$result" | grep -q "FOUND"; then
            pass "SketchUp installation verified"
        else
            die "SketchUp.exe not found after installation"
        fi
    fi
}

# ---------------------------------------------------------------------------
# Apply crack
# ---------------------------------------------------------------------------
apply_crack() {
    log "=== Applying SketchUp crack ==="

    # Check crack files exist
    local host_crack_dir="$SHARED_DIR/installers/SketchUp2025/Crack"
    if [[ ! -d "$host_crack_dir" ]]; then
        warn "Crack directory not found at $host_crack_dir — skipping crack"
        return 0
    fi

    # Kill any running SketchUp processes first
    "$WIN_EXEC" --no-connect --timeout 30 \
        "cmd /c taskkill /F /IM SketchUp.exe 2>nul & taskkill /F /IM LayOut.exe 2>nul & echo KILLED" \
        ".crack_kill_$$.txt" 2>/dev/null || true
    rm -f "$SHARED_DIR/.crack_kill_$$.txt" "$SHARED_DIR/.crack_kill_$$.txt.exitcode" 2>/dev/null || true
    sleep 2

    # Copy crack files
    "$WIN_EXEC" --timeout 60 \
        "cmd /c if exist \"${CRACK_DIR}\\SketchUp\\SketchUp.exe\" (copy \"${CRACK_DIR}\\SketchUp\\SketchUp.exe\" \"C:\\Program Files\\SketchUp\\SketchUp 2025\\\" /Y && echo SKETCHUP_CRACKED) else (echo NO_SKETCHUP_CRACK)" \
        ".crack_su_$$.txt" 2>/dev/null || true

    local result
    result=$(cat "$SHARED_DIR/.crack_su_$$.txt" 2>/dev/null || echo "")
    rm -f "$SHARED_DIR/.crack_su_$$.txt" "$SHARED_DIR/.crack_su_$$.txt.exitcode" 2>/dev/null || true

    if echo "$result" | grep -q "SKETCHUP_CRACKED"; then
        pass "SketchUp crack applied"
    else
        warn "SketchUp crack file not found, continuing"
    fi

    # Check LayOut crack
    "$WIN_EXEC" --timeout 60 \
        "cmd /c if exist \"${CRACK_DIR}\\LayOut\\LayOut.exe\" (copy \"${CRACK_DIR}\\LayOut\\LayOut.exe\" \"C:\\Program Files\\SketchUp\\SketchUp 2025\\LayOut\\\" /Y && echo LAYOUT_CRACKED) else (echo NO_LAYOUT_CRACK)" \
        ".crack_lo_$$.txt" 2>/dev/null || true

    local result2
    result2=$(cat "$SHARED_DIR/.crack_lo_$$.txt" 2>/dev/null || echo "")
    rm -f "$SHARED_DIR/.crack_lo_$$.txt" "$SHARED_DIR/.crack_lo_$$.txt.exitcode" 2>/dev/null || true

    if echo "$result2" | grep -q "LAYOUT_CRACKED"; then
        pass "LayOut crack applied"
    fi
}

# ---------------------------------------------------------------------------
# Suppress EULA
# ---------------------------------------------------------------------------
suppress_eula() {
    log "=== Suppressing SketchUp EULA ==="

    "$WIN_EXEC" --timeout 60 \
        "powershell -Command \"
\$prefsDir = \"\$env:LOCALAPPDATA\\SketchUp\\SketchUp 2025\\SketchUp\";
\$prefsFile = \"\$prefsDir\\PrivatePreferences.json\";
New-Item -ItemType Directory -Force -Path \$prefsDir | Out-Null;
\$prefs = @{
    'This Computer Only' = @{
        'Application' = @{ 'RunCounterSU' = 0 };
        'Common' = @{ 'AcceptedTerms' = \$true };
    }
};
\$prefs | ConvertTo-Json | Out-File -FilePath \$prefsFile -Encoding UTF8 -Force;
Write-Output EULA_SUPPRESSED
\"" \
        ".eula_$$.txt" 2>/dev/null || true

    local result
    result=$(cat "$SHARED_DIR/.eula_$$.txt" 2>/dev/null || echo "")
    rm -f "$SHARED_DIR/.eula_$$.txt" "$SHARED_DIR/.eula_$$.txt.exitcode" 2>/dev/null || true

    if echo "$result" | grep -q "EULA_SUPPRESSED"; then
        pass "EULA suppressed successfully"
    else
        warn "EULA suppression may have failed"
        echo "$result"
    fi
}

# ---------------------------------------------------------------------------
# Launch SketchUp
# ---------------------------------------------------------------------------
launch_sketchup() {
    log "=== Launching SketchUp ==="

    # Check if already running
    if "$WIN_EXEC" --no-connect --timeout 30 \
        "cmd /c tasklist /NH /FI \"IMAGENAME eq SketchUp.exe\" | findstr SketchUp" \
        ".launch_check_$$.txt" 2>/dev/null; then
        local result
        result=$(cat "$SHARED_DIR/.launch_check_$$.txt" 2>/dev/null || echo "")
        rm -f "$SHARED_DIR/.launch_check_$$.txt" "$SHARED_DIR/.launch_check_$$.txt.exitcode" 2>/dev/null || true
        if echo "$result" | grep -qi "SketchUp"; then
            pass "SketchUp already running"
            return 0
        fi
    fi
    rm -f "$SHARED_DIR/.launch_check_$$.txt" "$SHARED_DIR/.launch_check_$$.txt.exitcode" 2>/dev/null || true

    # Launch directly
    log "Launching SketchUp from: ${SU_EXE}"
    "$WIN_EXEC" --no-connect --timeout 30 \
        "cmd /c start \"\" \"${SU_EXE}\" && echo LAUNCHED" \
        ".launch_su_$$.txt" 2>/dev/null || true

    local result
    result=$(cat "$SHARED_DIR/.launch_su_$$.txt" 2>/dev/null || echo "")
    rm -f "$SHARED_DIR/.launch_su_$$.txt" "$SHARED_DIR/.launch_su_$$.txt.exitcode" 2>/dev/null || true

    if echo "$result" | grep -q "LAUNCHED"; then
        log "Launch command sent"
    else
        warn "Launch command output: $result"
    fi

    # Wait for plugin to start
    log "Waiting for plugin to become ready..."
    if "$WAIT_PLUGIN" --timeout 120; then
        pass "SketchUp and plugin are running"
        return 0
    else
        warn "Plugin not ready after launch — continuing anyway"
        return 1
    fi
}
# ---------------------------------------------------------------------------
# Auto-start Scripts
# ---------------------------------------------------------------------------
auto_start() {
    log "=== Deploying auto-start scripts ==="

    local vbs_src="$SCRIPT_DIR/../oem/launch_sketchup.vbs"
    local ps1_src="$SCRIPT_DIR/../oem/launch_sketchup.ps1"

    # Validate source files exist on host
    if [[ ! -f "$vbs_src" ]]; then
        die "launch_sketchup.vbs not found at $vbs_src"
    fi
    if [[ ! -f "$ps1_src" ]]; then
        die "launch_sketchup.ps1 not found at $ps1_src"
    fi

    # Step 1: Copy VBS/PS1 into shared folder so Windows can access them
    log "  Copying source files to shared folder..."
    cp "$vbs_src" "$SHARED_DIR/.launch_sketchup.vbs"
    cp "$ps1_src" "$SHARED_DIR/.launch_sketchup.ps1"

    local startup_path='C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp'
    local oem_path='C:\OEM'
    local shared_win='C:\Users\Docker\Desktop\Shared'

    # Step 2: Deploy PS1 to C:\OEM\ (persistent)
    log "  Deploying launch_sketchup.ps1 to $oem_path..."
    "$WIN_EXEC" --timeout 60 \
        "powershell -Command \"& { mkdir '${oem_path}' -Force | Out-Null; Copy-Item '${shared_win}\.launch_sketchup.ps1' '${oem_path}\launch_sketchup.ps1' -Force; if (Test-Path '${oem_path}\launch_sketchup.ps1') { Write-Output OEM_PS1_OK } else { Write-Output OEM_PS1_FAIL } }\"" \
        ".auto_start_ps1_$$.txt" 2>/dev/null || true

    local ps1_result
    ps1_result=$(cat "$SHARED_DIR/.auto_start_ps1_$$.txt" 2>/dev/null || echo "")
    rm -f "$SHARED_DIR/.auto_start_ps1_$$.txt" "$SHARED_DIR/.auto_start_ps1_$$.txt.exitcode" 2>/dev/null || true

    if echo "$ps1_result" | grep -q "OEM_PS1_OK"; then
        pass "launch_sketchup.ps1 deployed to $oem_path"
    else
        warn "launch_sketchup.ps1 deployment result: $ps1_result"
    fi

    # Step 3: Deploy VBS to startup folder
    log "  Deploying launch_sketchup.vbs to startup folder..."
    "$WIN_EXEC" --timeout 30 \
        "powershell -Command \"& { Copy-Item '${shared_win}\.launch_sketchup.vbs' '${startup_path}\launch_sketchup.vbs' -Force; if (Test-Path '${startup_path}\launch_sketchup.vbs') { Write-Output VBS_OK } else { Write-Output VBS_FAIL } }\"" \
        ".auto_start_vbs_$$.txt" 2>/dev/null || true

    local vbs_result
    vbs_result=$(cat "$SHARED_DIR/.auto_start_vbs_$$.txt" 2>/dev/null || echo "")
    rm -f "$SHARED_DIR/.auto_start_vbs_$$.txt" "$SHARED_DIR/.auto_start_vbs_$$.txt.exitcode" 2>/dev/null || true

    if echo "$vbs_result" | grep -q "VBS_OK"; then
        pass "launch_sketchup.vbs deployed to startup folder"
    else
        warn "launch_sketchup.vbs deployment result: $vbs_result"
    fi

    # Clean up temp files from shared folder
    rm -f "$SHARED_DIR/.launch_sketchup.vbs" "$SHARED_DIR/.launch_sketchup.ps1" 2>/dev/null || true

    log "Auto-start deployment complete"
}

auto_start_remove() {
    log "=== Removing auto-start scripts ==="

    local startup_path='C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp'
    local oem_path='C:\OEM'

    "$WIN_EXEC" --timeout 30 \
        "cmd /c del \"${startup_path}\\launch_sketchup.vbs\" 2>nul & del \"${oem_path}\\launch_sketchup.ps1\" 2>nul & echo REMOVED" \
        ".auto_start_rm_$$.txt" 2>/dev/null || true

    local result
    result=$(cat "$SHARED_DIR/.auto_start_rm_$$.txt" 2>/dev/null || echo "")
    rm -f "$SHARED_DIR/.auto_start_rm_$$.txt" "$SHARED_DIR/.auto_start_rm_$$.txt.exitcode" 2>/dev/null || true

    pass "Auto-start scripts removed"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║    SketchUp + Plugin Installer               ║"
echo "╚══════════════════════════════════════════════╝"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --plugin-only) PLUGIN_ONLY=true; shift ;;
        --status)      STATUS_ONLY=true; shift ;;
        --auto-start)  AUTO_START=true; shift ;;
        --remove)      AUTO_START_REMOVE=true; shift ;;
        -h|--help)
            echo "Usage: sketchup-install.sh [--plugin-only] [--status] [--auto-start [--remove]]"
            echo ""
            echo "  --plugin-only           Only install/reinstall the SketchUp Link plugin"
            echo "  --status                Check installation status only"
            echo "  --auto-start            Deploy auto-start scripts (SketchUp launches on Windows login)"
            echo "  --auto-start --remove   Remove auto-start scripts"
            exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

if [[ "$STATUS_ONLY" == "true" ]]; then
    check_status
    exit $?
fi

if [[ "$PLUGIN_ONLY" == "true" ]]; then
    echo ""
    log "Plugin-only mode"
    install_plugin
    echo ""
    log "=== Installation complete ==="
    exit 0
fi
if [[ "$AUTO_START" == "true" ]]; then
    echo ""
    if [[ "$AUTO_START_REMOVE" == "true" ]]; then
        auto_start_remove
    else
        auto_start
    fi
    echo ""
    log "=== Done ==="
    exit 0
fi


# Full install
echo ""

# Step 1: Check current status
check_status && {
    log "Everything already installed and running. Skipping."
    exit 0
}

echo ""

# Step 2: Install SketchUp
install_sketchup

echo ""

# Step 3: Apply crack
apply_crack

echo ""

# Step 4: Install plugin
install_plugin

echo ""

# Step 5: Suppress EULA
suppress_eula

echo ""

# Step 6: Launch SketchUp
launch_sketchup

echo ""
log "=== Installation complete ==="
