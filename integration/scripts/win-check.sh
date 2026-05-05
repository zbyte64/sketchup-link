#!/usr/bin/env bash
# win-check.sh — Verify state inside Windows VM: process running, file exists,
# port listening, or combined --sketchup-ready.
#
# Uses win-exec.sh internally for all checks.
#
# Usage:
#   win-check.sh --process SketchUp.exe
#   win-check.sh --file "C:\Program Files\SketchUp\SketchUp 2025\SketchUp.exe"
#   win-check.sh --port 9876
#   win-check.sh --sketchup-ready
#   win-check.sh --sketchup-installed
#   win-check.sh --all               # Run every check

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIN_EXEC="$SCRIPT_DIR/win-exec.sh"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { echo "[win-check] $*"; }
die()  { log "FATAL: $*"; exit 1; }
pass() { log "PASS: $*"; }
fail() { log "FAIL: $*"; HAS_FAILURE=true; }

HAS_FAILURE=false

# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------

check_process() {
    local name="$1"
    log "Checking process: $name"
    local outfile=".check_process_$$.txt"
    local exitfile=".check_process_$$.txt.exitcode"


    # Use win-exec with --no-connect to reuse existing session
    if "$WIN_EXEC" --no-connect "cmd /c tasklist /NH /FI \"IMAGENAME eq ${name}\" 2>&1" "$outfile" 2>/dev/null; then
        local result
        result=$(cat "$SCRIPT_DIR/../shared/$outfile" 2>/dev/null || echo "")
        if echo "$result" | grep -qi "$name"; then
            pass "Process '$name' is running"
            echo "$result" | head -5
            return 0
        fi
    fi

    fail "Process '$name' is NOT running"
    return 1
}

check_file() {
    local path="$1"
    log "Checking file: $path"
    local outfile=".check_file_$$.txt"



    if "$WIN_EXEC" --no-connect "cmd /c if exist \"${path}\" (echo FOUND) else (echo NOTFOUND)" "$outfile" 2>/dev/null; then
        local result
        result=$(cat "$SCRIPT_DIR/../shared/$outfile" 2>/dev/null || echo "")
        if echo "$result" | grep -qi "FOUND"; then
            pass "File exists: $path"
            return 0
        fi
    fi

    fail "File NOT found: $path"
    return 1
}

check_port() {
    local port="$1"
    log "Checking port: $port"
    local outfile=".check_port_$$.txt"



    if "$WIN_EXEC" --no-connect "cmd /c netstat -an | findstr /i \"LISTENING\" | findstr \":${port}\"" "$outfile" 2>/dev/null; then
        local result
        result=$(cat "$SCRIPT_DIR/../shared/$outfile" 2>/dev/null || echo "")
        if echo "$result" | grep -qi ":${port}"; then
            pass "Port $port is LISTENING"
            echo "$result" | head -3
            return 0
        fi
    fi

    fail "Port $port is NOT listening"
    return 1
}

check_plugin_http() {
    log "Checking plugin HTTP endpoint at 127.0.0.1:9876/status"
    local host="127.0.0.1"
    local port="9876"

    # Check from host (port forwarded from container)
    if curl -s --connect-timeout 5 --max-time 10 "http://${host}:${port}/status" >/dev/null 2>&1; then
        local status_code
        status_code=$(curl -s -o /dev/null -w "%{http_code}" "http://${host}:${port}/status" 2>/dev/null || echo "000")
        pass "Plugin HTTP endpoint returns HTTP $status_code"
        return 0
    fi

    fail "Plugin HTTP endpoint not responding"
    return 1
}

check_iptables_dnat() {
    log "Checking iptables DNAT for port 9876"
    if docker exec windows iptables -t nat -L PREROUTING 2>/dev/null | grep -q "9876"; then
        pass "iptables DNAT rule for port 9876 exists"
        docker exec windows iptables -t nat -L PREROUTING 2>/dev/null | grep "9876" | head -3
        return 0
    fi

    # Alternative: check docker-proxy
    if command -v ss &>/dev/null; then
        if ss -tlnp | grep -q "9876"; then
            pass "Port 9876 is listening on host (docker-proxy)"
            return 0
        fi
    fi

    fail "No DNAT rule for port 9876 found"
    return 1
}

check_sketchup_installed() {
    log "Checking if SketchUp is installed"
    local base_path='C:\Program Files\SketchUp\SketchUp 2025'
    local exe_path="${base_path}\SketchUp\SketchUp.exe"
    local plugin_ext='C:\Users\Docker\AppData\Roaming\SketchUp\SketchUp 2025\SketchUp\Extensions\sketchup_link.rb'

    local all_ok=true

    check_file "$exe_path" || all_ok=false
    check_file "$plugin_ext" || all_ok=false

    if [[ "$all_ok" == "true" ]]; then
        pass "SketchUp is installed with plugin"
    else
        fail "SketchUp installation incomplete"
    fi
}

check_sketchup_ready() {
    log "=== SketchUp Ready Check ==="
    echo ""

    check_process "SketchUp.exe" || true
    check_plugin_http || true
    check_port "9876" || true
    check_iptables_dnat || true

    echo ""
    if [[ "$HAS_FAILURE" == "false" ]]; then
        pass "SketchUp is fully ready (running, plugin responsive, port accessible)"
        return 0
    else
        fail "SketchUp is NOT fully ready — check individual results above"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if [[ $# -eq 0 ]]; then
    echo "Usage: win-check.sh [--process <name>] [--file <path>] [--port <port>] [--sketchup-ready] [--sketchup-installed] [--all]"
    echo ""
    echo "Checks are run via win-exec.sh inside the Windows VM."
    echo "Multiple checks can be combined; all are evaluated."
    exit 0
fi

ALL=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --process)    check_process "$2"; shift 2 ;;
        --file)       check_file "$2"; shift 2 ;;
        --port)       check_port "$2"; shift 2 ;;
        --sketchup-ready)
            check_sketchup_ready
            shift ;;
        --sketchup-installed)
            check_sketchup_installed
            shift ;;
        --plugin-http)
            check_plugin_http
            shift ;;
        --iptables)
            check_iptables_dnat
            shift ;;
        --all)
            ALL=true
            shift ;;
        -h|--help)
            sed -n '2,10p' "$0"
            exit 0 ;;
        *)
            echo "ERROR: Unknown option: $1"
            exit 1 ;;
    esac
done

if [[ "$ALL" == "true" ]]; then
    echo "=== Running all checks ==="
    echo ""
    echo "--- Process ---"
    check_process "SketchUp.exe" || true
    echo ""
    echo "--- File ---"
    check_file 'C:\Program Files\SketchUp\SketchUp 2025\SketchUp.exe' || true
    echo ""
    echo "--- Port ---"
    check_port "9876" || true
    echo ""
    echo "--- iptables ---"
    check_iptables_dnat || true
    echo ""
    echo "--- Plugin HTTP ---"
    check_plugin_http || true
    echo ""
    echo "--- SketchUp Ready ---"
    check_sketchup_ready || true
fi

if [[ "$HAS_FAILURE" == "true" ]]; then
    exit 1
fi
exit 0
