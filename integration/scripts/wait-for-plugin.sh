#!/usr/bin/env bash
# wait-for-plugin.sh — Poll the SketchUp Link plugin HTTP server with
# progressive diagnostics on failure.
#
# Usage:
#   wait-for-plugin.sh --host 127.0.0.1 --port 9876 --timeout 300
#   wait-for-plugin.sh                          # Uses defaults
#
# Progressive diagnostics:
#   - Every poll: checks sentinel file (sketchup_status.json from launch_sketchup.ps1)
#   - After 30s: takes QEMU screenshot
#   - After 35s: checks for ToS/EULA dialog and dismisses it
#   - After 60s: checks SketchUp process, plugin file, and port
#   - After 90s: attempts auto-remediation (dismiss ToS, launch SketchUp, re-install plugin)
#   - On timeout: collects full diagnostic report

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIN_EXEC="$SCRIPT_DIR/win-exec.sh"
WIN_CHECK="$SCRIPT_DIR/win-check.sh"
WIN_SCREENSHOT="$SCRIPT_DIR/win-screenshot.sh"

SHARED_DIR="$(cd "$SCRIPT_DIR/../shared" && pwd)"
HOST="127.0.0.1"
PORT="9876"
TIMEOUT=300          # total timeout in seconds
POLL_INTERVAL=5      # seconds between polls
CONNECT_TIMEOUT=3    # seconds for curl connect timeout
CONTAINER="windows"

# Diagnostic state
DIAG_DIR="$SCRIPT_DIR/diagnostics"
START_TIME=""
DIAG_COLLECTED=false
TOS_CHECKED=false
LAUNCH_ATTEMPTED=false
# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)    HOST="$2"; shift 2 ;;
        --port)    PORT="$2"; shift 2 ;;
        --timeout) TIMEOUT="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: wait-for-plugin.sh [--host HOST] [--port PORT] [--timeout SECS]"
            echo ""
            echo "Polls GET http://HOST:PORT/status until the plugin responds."
            echo "Collects progressive diagnostics on failure, including"
            echo "auto-remediation attempts."
            exit 0 ;;
        *) echo "ERROR: Unknown option: $1"; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() { echo "[wait-for-plugin] $(date '+%H:%M:%S') $*"; }
die() { log "FATAL: $*"; exit 1; }

collect_diagnostics() {
    if [[ "$DIAG_COLLECTED" == "true" ]]; then
        return
    fi
    DIAG_COLLECTED=true

    mkdir -p "$DIAG_DIR"
    local ts
    ts=$(date '+%Y%m%d_%H%M%S')
    local base="${DIAG_DIR}/${ts}_plugin_diag"
    local report="${base}_report.txt"

    log "=== Collecting diagnostics ==="

    {
        echo "========================================================"
        echo "Plugin Diagnostics Report"
        echo "Timestamp: $(date)"
        echo "Host: ${HOST}:${PORT}"
        echo "Timeout: ${TIMEOUT}s"
        echo "========================================================"
        echo ""
    } > "$report"

    # 1. Screenshot (QEMU)
    log "  Screenshot via QEMU..."
    if "$WIN_SCREENSHOT" --qemu "plugin_diag_${ts}" 2>/dev/null; then
        echo "[OK] QEMU screenshot captured" >> "$report"
    else
        echo "[FAIL] QEMU screenshot failed" >> "$report"
    fi

    # 2. Try RDP screenshot
    log "  Screenshot via RDP..."
    if "$WIN_SCREENSHOT" --rdp "plugin_diag_rdp_${ts}" 2>/dev/null; then
        echo "[OK] RDP screenshot captured" >> "$report"
    else
        echo "[FAIL] RDP screenshot failed" >> "$report"
    fi

    # 3. Check SketchUp process
    log "  Checking SketchUp process..."
    echo "" >> "$report"
    echo "--- Process: SketchUp.exe ---" >> "$report"
    "$WIN_EXEC" --no-connect --timeout 30 \
        "cmd /c tasklist /NH /FI \"IMAGENAME eq SketchUp.exe\"" \
        ".diag_tasklist_$$.txt" 2>/dev/null || true
    cat "$SCRIPT_DIR/../shared/.diag_tasklist_$$.txt" 2>/dev/null >> "$report" || echo "(unavailable)" >> "$report"
    rm -f "$SCRIPT_DIR/../shared/.diag_tasklist_$$.txt" "$SCRIPT_DIR/../shared/.diag_tasklist_$$.txt.exitcode" 2>/dev/null || true

    # 4. Check plugin file
    log "  Checking plugin file..."
    echo "" >> "$report"
    echo "--- Plugin file ---" >> "$report"
    "$WIN_EXEC" --no-connect --timeout 30 \
        "cmd /c if exist \"C:\\Users\\Docker\\AppData\\Roaming\\SketchUp\\SketchUp 2025\\SketchUp\\Extensions\\sketchup_link.rb\" (echo FOUND) else (echo NOTFOUND)" \
        ".diag_plugin_$$.txt" 2>/dev/null || true
    cat "$SCRIPT_DIR/../shared/.diag_plugin_$$.txt" 2>/dev/null >> "$report" || echo "(unavailable)" >> "$report"
    rm -f "$SCRIPT_DIR/../shared/.diag_plugin_$$.txt" "$SCRIPT_DIR/../shared/.diag_plugin_$$.txt.exitcode" 2>/dev/null || true

    # 5. Check SketchUp.exe
    log "  Checking SketchUp executable..."
    echo "" >> "$report"
    echo "--- SketchUp executable ---" >> "$report"
    "$WIN_EXEC" --no-connect --timeout 30 \
        "cmd /c if exist \"C:\\Program Files\\SketchUp\\SketchUp 2025\\SketchUp\\SketchUp.exe\" (echo FOUND) else (echo NOTFOUND)" \
        ".diag_su_$$.txt" 2>/dev/null || true
    cat "$SCRIPT_DIR/../shared/.diag_su_$$.txt" 2>/dev/null >> "$report" || echo "(unavailable)" >> "$report"
    rm -f "$SCRIPT_DIR/../shared/.diag_su_$$.txt" "$SCRIPT_DIR/../shared/.diag_su_$$.txt.exitcode" 2>/dev/null || true

    # 6. Check port listening
    log "  Checking port 9876..."
    echo "" >> "$report"
    echo "--- Port 9876 (netstat inside Windows) ---" >> "$report"
    "$WIN_EXEC" --no-connect --timeout 30 \
        "cmd /c netstat -an | findstr \":${PORT}\"" \
        ".diag_port_$$.txt" 2>/dev/null || true
    cat "$SCRIPT_DIR/../shared/.diag_port_$$.txt" 2>/dev/null >> "$report" || echo "(unavailable)" >> "$report"
    rm -f "$SCRIPT_DIR/../shared/.diag_port_$$.txt" "$SCRIPT_DIR/../shared/.diag_port_$$.txt.exitcode" 2>/dev/null || true

    # 7. Check iptables
    log "  Checking iptables DNAT..."
    echo "" >> "$report"
    echo "--- iptables DNAT ---" >> "$report"
    docker exec "$CONTAINER" iptables -t nat -L PREROUTING 2>/dev/null >> "$report" || echo "(container not accessible)" >> "$report"

    # 8. Container logs
    echo "" >> "$report"
    echo "--- Windows container logs (tail 20) ---" >> "$report"
    docker logs "$CONTAINER" --tail 20 2>/dev/null >> "$report" || true

    # 9. Check docker-proxy
    echo "" >> "$report"
    echo "--- Host port listeners ---" >> "$report"
    ss -tlnp 2>/dev/null | grep -E "9876|3389" >> "$report" || true

    log "  Diagnostics saved to $report"
    echo "============================================" >> "$report"
    log "=== Diagnostics complete ==="
}

attempt_launch_sketchup() {
    log "Attempting to launch SketchUp via agent-rdp..."
    echo ""

    # Try: Run SketchUp via automate run
    log "  Method 1: automate run"
    "$WIN_EXEC" --no-connect --timeout 30 \
        "cmd /c start \"\" \"C:\\Program Files\\SketchUp\\SketchUp 2025\\SketchUp\\SketchUp.exe\"" \
        ".launch_method1_$$.txt" 2>/dev/null || true
    rm -f "$SCRIPT_DIR/../shared/.launch_method1_$$.txt" "$SCRIPT_DIR/../shared/.launch_method1_$$.txt.exitcode" 2>/dev/null || true

    sleep 15

    # Check if it's running
    if "$WIN_EXEC" --no-connect --timeout 30 \
        "cmd /c tasklist /NH /FI \"IMAGENAME eq SketchUp.exe\" | findstr SketchUp" \
        ".launch_check_$$.txt" 2>/dev/null; then
        log "  SketchUp launched successfully (Method 1)"
        rm -f "$SCRIPT_DIR/../shared/.launch_check_$$.txt" "$SCRIPT_DIR/../shared/.launch_check_$$.txt.exitcode" 2>/dev/null || true
        return 0
    fi
    rm -f "$SCRIPT_DIR/../shared/.launch_check_$$.txt" "$SCRIPT_DIR/../shared/.launch_check_$$.txt.exitcode" 2>/dev/null || true

    # Method 2: Start menu via agent-rdp keyboard
    log "  Method 2: Start menu via keyboard"
    agent-rdp --session sketchup-link keyboard press "win" 2>/dev/null || true
    sleep 1
    agent-rdp --session sketchup-link keyboard type "sketchup" 2>/dev/null || true
    sleep 2
    agent-rdp --session sketchup-link keyboard press "enter" 2>/dev/null || true

    sleep 20

    if "$WIN_EXEC" --no-connect --timeout 30 \
        "cmd /c tasklist /NH /FI \"IMAGENAME eq SketchUp.exe\" | findstr SketchUp" \
        ".launch_check2_$$.txt" 2>/dev/null; then
        log "  SketchUp launched successfully (Method 2)"
        rm -f "$SCRIPT_DIR/../shared/.launch_check2_$$.txt" "$SCRIPT_DIR/../shared/.launch_check2_$$.txt.exitcode" 2>/dev/null || true
        return 0
    fi
    rm -f "$SCRIPT_DIR/../shared/.launch_check2_$$.txt" "$SCRIPT_DIR/../shared/.launch_check2_$$.txt.exitcode" 2>/dev/null || true

    log "  WARNING: Failed to launch SketchUp"
    return 1
}
# ---------------------------------------------------------------------------
# ToS / EULA dialog dismissal
# ---------------------------------------------------------------------------
dismiss_tos_dialog() {
    log "Checking for Terms of Service / EULA dialog..."
    local found=false
    local box x y cx cy

    # Try multiple search terms for the dialog button and window title
    for search_term in "Agree" "Accept" "I Agree" "Terms" "License" "EULA"; do
        if box=$(agent-rdp --session sketchup-link locate "$search_term" 2>/dev/null); then
            log "  Found '$search_term' on screen — dismissing dialog"
            # Parse numeric coordinates from locate output
            # Output format: "Agree" found at (123,456)-(789,012)
            # Extract first number (x) and second number (y) from the first coordinate pair
            x=$(echo "$box" | grep -oP '(?<=\()\d+' | head -1)
            y=$(echo "$box" | grep -oP '(?<=,\s*)\d+' | head -1)
            if [[ -n "$x" && -n "$y" ]]; then
                cx=$((x + 10))
                cy=$((y + 10))
                agent-rdp --session sketchup-link mouse click "$cx" "$cy" 2>/dev/null || true
                log "  Clicked '$search_term' at approx ($cx, $cy)"
                found=true
                break
            fi
        fi
    done

    if [[ "$found" == "true" ]]; then
        sleep 5
        log "  ToS dialog dismissed, re-checking plugin..."
        return 0
    fi

    # Fallback: Tab to navigate to default button + Enter
    log "  Trying Tab+Enter fallback..."
    agent-rdp --session sketchup-link keyboard press "tab" 2>/dev/null || true
    sleep 0.5
    agent-rdp --session sketchup-link keyboard press "tab" 2>/dev/null || true
    sleep 0.5
    agent-rdp --session sketchup-link keyboard press "tab" 2>/dev/null || true
    sleep 0.5
    agent-rdp --session sketchup-link keyboard press "enter" 2>/dev/null || true
    sleep 3

    # Brute-force Enter dismiss
    log "  Brute-force Enter..."
    agent-rdp --session sketchup-link keyboard press "enter" 2>/dev/null || true
    sleep 3

    # Also check for "SketchUp" title bar with "Not Responding" pattern
    log "  Checking for 'Not Responding' title bars..."
    if box=$(agent-rdp --session sketchup-link locate "Not Responding" 2>/dev/null); then
        log "  Found 'Not Responding' — SketchUp may be hung"
        screenshot_name=$(date '+%Y%m%d_%H%M%S')_not_responding
        "$WIN_SCREENSHOT" --rdp "not_responding_${screenshot_name}" 2>/dev/null || true
    fi

    log "  ToS dismissal attempts completed"
    return 0
}


# ---------------------------------------------------------------------------
# Main poll loop
# ---------------------------------------------------------------------------
log "Waiting for plugin at http://${HOST}:${PORT}/status"
log "Timeout: ${TIMEOUT}s, Poll interval: ${POLL_INTERVAL}s"
echo ""

START_TIME=$(date +%s)

while true; do
    ELAPSED=$(( $(date +%s) - START_TIME ))

    # Try HTTP request
    if curl -s --connect-timeout "$CONNECT_TIMEOUT" --max-time 10 "http://${HOST}:${PORT}/status" >/dev/null 2>&1; then
        local status_code
        status_code=$(curl -s -o /dev/null -w "%{http_code}" \
            --connect-timeout "$CONNECT_TIMEOUT" \
            "http://${HOST}:${PORT}/status" 2>/dev/null || echo "000")
        log "Plugin READY after ${ELAPSED}s (HTTP $status_code)"
        echo ""
        exit 0
    fi

    # Also check for sentinel file in shared folder (written by launch_sketchup.ps1)
    sentinel="$SHARED_DIR/sketchup_status.json"
    if [[ -f "$sentinel" ]]; then
        sentinel_status=$(grep -o '"status":"[^"]*"' "$sentinel" 2>/dev/null | cut -d'"' -f4 || echo "")
        if [[ "$sentinel_status" == "ready" ]] || [[ "$sentinel_status" == "running" ]]; then
            log "Sentinel file reports status: $sentinel_status after ${ELAPSED}s"
        fi
    fi

    # Progressive diagnostics
    if [[ $ELAPSED -ge 90 ]] && [[ "$LAUNCH_ATTEMPTED" == "false" ]]; then
        if [[ "$DIAG_COLLECTED" == "false" ]]; then
            log "Plugin not responding after 90s — collecting diagnostics + auto-remediation"
            echo ""
            collect_diagnostics
            echo ""
        fi
        # Check for ToS dialog before attempting launch
        dismiss_tos_dialog || true
        TOS_CHECKED=true
        # Attempt to launch SketchUp
        attempt_launch_sketchup || true
        LAUNCH_ATTEMPTED=true
        echo ""
        # Continue polling (don't reset timer)
    elif [[ $ELAPSED -ge 60 ]] && [[ "$DIAG_COLLECTED" == "false" ]]; then
        log "Plugin not responding after 60s — checking state..."
        echo ""
        "$WIN_CHECK" --sketchup-ready || true
        echo ""
    elif [[ $ELAPSED -ge 35 ]] && [[ "$TOS_CHECKED" == "false" ]]; then
        log "Plugin not responding after 35s — checking for ToS dialog..."
        echo ""
        dismiss_tos_dialog || true
        TOS_CHECKED=true
        echo ""
    elif [[ $ELAPSED -ge 30 ]] && [[ "$TOS_CHECKED" == "false" ]]; then
        log "Plugin not responding after 30s — taking diagnostic screenshot..."
        "$WIN_SCREENSHOT" --qemu "plugin_unresponsive_30s" 2>/dev/null || true
        echo ""
    fi

    if [[ $ELAPSED -ge $TIMEOUT ]]; then
        log "TIMEOUT after ${TIMEOUT}s — plugin never responded"
        if [[ "$DIAG_COLLECTED" == "false" ]]; then
            collect_diagnostics
        fi
        exit 1
    fi

    sleep "$POLL_INTERVAL"
done
