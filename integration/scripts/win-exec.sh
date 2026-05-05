#!/usr/bin/env bash
# win-exec.sh — Reliable command execution inside Windows with output capture.
#
# Connects agent-rdp (if not already connected), writes a PowerShell wrapper
# script to the shared folder, executes it via `automate run`, captures
# stdout/stderr and exit code, and polls for completion.
#
# Usage:
#   win-exec.sh "cmd /c dir C:\\Program Files\\SketchUp" output.txt
#   win-exec.sh --timeout 300 "powershell -File C:\\OEM\\install_sketchup.ps1" install_log.txt
#   win-exec.sh --no-connect "ipconfig /all" network.txt

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMEOUT=120
POLL_INTERVAL=2
RDP_HOST="127.0.0.1"
RDP_PORT=3389
RDP_USER="Docker"
RDP_PASS="admin"
SHARED_DIR="$(cd "$SCRIPT_DIR/../shared" && pwd)"
CONTAINER="windows"
NO_CONNECT=false
RDP_SESSION="sketchup-link"

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --timeout)
            TIMEOUT="$2"; shift 2 ;;
        --no-connect)
            NO_CONNECT=true; shift ;;
        -h|--help)
            echo "Usage: win-exec.sh [--timeout SECS] [--no-connect] <command> <output_filename>"
            echo ""
            echo "Runs <command> inside Windows via agent-rdp automate run."
            echo "Writes a PowerShell wrapper script to shared/, executes it,"
            echo "captures stdout+stderr into shared/<output_filename>"
            echo "and exit code into shared/<output_filename>.exitcode."
            exit 0 ;;
        -*)
            echo "ERROR: Unknown option: $1"; exit 1 ;;
        *)
            break ;;
    esac
done

if [[ $# -lt 2 ]]; then
    echo "ERROR: Usage: win-exec.sh [--timeout SECS] <command> <output_filename>"
    exit 1
fi

COMMAND="$1"
OUTFILE="$2"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()   { echo "[win-exec] $(date '+%H:%M:%S') $*"; }
die()   { log "FATAL: $*"; exit 1; }
warn()  { log "WARNING: $*"; }

collect_diagnostics() {
    local label="$1"
    local diag_dir="$SCRIPT_DIR/diagnostics"
    mkdir -p "$diag_dir"
    local ts
    ts=$(date '+%Y%m%d_%H%M%S')
    local base="${diag_dir}/${ts}_${label}"

    log "Collecting diagnostics to ${base}_*"

    if docker exec "$CONTAINER" sh -c 'nc -z 127.0.0.1 7100 2>/dev/null' 2>/dev/null; then
        docker exec "$CONTAINER" sh -c '
            echo "screendump /tmp/win_exec_diag.ppm" | timeout 5 nc 127.0.0.1 7100
        ' 2>/dev/null || true
        docker cp "${CONTAINER}:/tmp/win_exec_diag.ppm" "${base}_screendump.ppm" 2>/dev/null || true
        if command -v convert &>/dev/null && [[ -f "${base}_screendump.ppm" ]]; then
            convert "${base}_screendump.ppm" "${base}_screendump.png" 2>/dev/null || true
        fi
    fi

    if agent-rdp --session "$RDP_SESSION" session info &>/dev/null; then
        agent-rdp --session "$RDP_SESSION" screenshot -o "${base}_rdp.png" 2>/dev/null || true
    fi
}

agent_rdp_cmd() {
    # Use agent-rdp with or without npx prefix
    if command -v agent-rdp &>/dev/null; then
        agent-rdp "$@"
    else
        npx agent-rdp "$@"
    fi
}

# ---------------------------------------------------------------------------
# Phase 1: Connect agent-rdp
# ---------------------------------------------------------------------------
if [[ "$NO_CONNECT" != "true" ]]; then
    if agent_rdp_cmd --session "$RDP_SESSION" session info &>/dev/null; then
        log "agent-rdp session '$RDP_SESSION' already connected"
    else
        log "Connecting agent-rdp to ${RDP_HOST}:${RDP_PORT}..."
        agent_rdp_cmd --session "$RDP_SESSION" connect \
            --host "$RDP_HOST" \
            -u "$RDP_USER" \
            -p "$RDP_PASS" \
            --enable-win-automation \
            --drive "$SHARED_DIR:Shared" 2>&1 || \
            die "Failed to connect agent-rdp"
        log "agent-rdp connected"
        sleep 2
    fi
fi

# ---------------------------------------------------------------------------
# Phase 2: Write PowerShell wrapper script to shared folder
# ---------------------------------------------------------------------------
# We write the script as a .ps1 file in the shared folder. This avoids all
# quoting/escaping issues with inline PowerShell commands passed through
# agent-rdp / Windows cmd.exe / PowerShell parser chain.
#
# The script writes stdout+stderr and exit code to the shared folder.

PS_SCRIPT_NAME=".win_exec_script_$$.ps1"
HOST_PS_SCRIPT="$SHARED_DIR/$PS_SCRIPT_NAME"
WIN_PS_SCRIPT="C:\\Users\\Docker\\Desktop\\Shared\\$PS_SCRIPT_NAME"
WIN_OUTFILE="C:\\Users\\Docker\\Desktop\\Shared\\$OUTFILE"
WIN_EXITFILE="${WIN_OUTFILE}.exitcode"

# Clean up any previous output
rm -f "$SHARED_DIR/$OUTFILE" "$SHARED_DIR/$OUTFILE.exitcode"

# Generate PowerShell wrapper script.
# We write it to the shared folder so Windows can execute it directly.
# Single quotes in $COMMAND are doubled for PowerShell escaping.
PS_ESC_COMMAND=$(echo "$COMMAND" | sed "s/'/''/g")

cat > "$HOST_PS_SCRIPT" << PSEOF
\$command = '${PS_ESC_COMMAND}'
\$outFile = '${WIN_OUTFILE}'
\$exitFile = '${WIN_EXITFILE}'

try {
    \$result = & cmd.exe '/c' \$command 2>&1
    \$exitCode = \$LASTEXITCODE
    \$result | Out-File -FilePath \$outFile -Encoding UTF8 -Force
    \$exitCode | Out-File -FilePath \$exitFile -Encoding UTF8 -Force
} catch {
    \$_.Exception.Message | Out-File -FilePath \$outFile -Encoding UTF8 -Force
    1 | Out-File -FilePath \$exitFile -Encoding UTF8 -Force
}
PSEOF

log "PowerShell wrapper written: $HOST_PS_SCRIPT"
log "Running command: $COMMAND"
log "Output file: $SHARED_DIR/$OUTFILE"
log "Timeout: ${TIMEOUT}s"

# ---------------------------------------------------------------------------
# Phase 3: Execute via agent-rdp
# ---------------------------------------------------------------------------
log "Executing via agent-rdp..."

agent_rdp_cmd --session "$RDP_SESSION" automate run \
    "powershell -ExecutionPolicy Bypass -NoProfile -File \"$WIN_PS_SCRIPT\"" \
    --wait \
    --process-timeout "$((TIMEOUT * 1000))" 2>&1 || \
    warn "agent-rdp returned non-zero (command may have failed on Windows side)"

# ---------------------------------------------------------------------------
# Phase 4: Poll for output file
# ---------------------------------------------------------------------------
HOST_OUTFILE="$SHARED_DIR/$OUTFILE"
HOST_EXITFILE="$SHARED_DIR/$OUTFILE.exitcode"
START_TIME=$(date +%s)

while true; do
    ELAPSED=$(( $(date +%s) - START_TIME ))

    if [[ -f "$HOST_EXITFILE" ]]; then
        EXIT_CODE=$(cat "$HOST_EXITFILE" 2>/dev/null | tr -cd '0-9' || echo "-1")
        log "Command completed in ${ELAPSED}s, exit code: $EXIT_CODE"
        if [[ -f "$HOST_OUTFILE" ]]; then
            log "Output file: lines=$(wc -l < "$HOST_OUTFILE")"
        else
            log "WARNING: Exit file found but output file missing"
        fi
        # Clean up wrapper script
        rm -f "$HOST_PS_SCRIPT" 2>/dev/null || true
        exit "$EXIT_CODE"
    fi

    if [[ $ELAPSED -ge $TIMEOUT ]]; then
        log "TIMEOUT after ${TIMEOUT}s — command did not produce output"
        collect_diagnostics "win_exec_timeout"
        # Clean up
        rm -f "$HOST_PS_SCRIPT" 2>/dev/null || true
        die "Command timed out: $COMMAND"
    fi

    sleep "$POLL_INTERVAL"
done
