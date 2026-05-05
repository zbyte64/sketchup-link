#!/usr/bin/env bash
# win-screenshot.sh — Capture screenshots via QEMU screendump or agent-rdp.
#
# Usage:
#   win-screenshot.sh --qemu output_name       # Fast, always works (PPM → PNG)
#   win-screenshot.sh --rdp output_name        # Higher quality via RDP
#   win-screenshot.sh --locate "text"          # OCR via agent-rdp
#   win-screenshot.sh --locate "text" --action click  # Find + click

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARED_DIR="$(cd "$SCRIPT_DIR/../shared" && pwd)"
SCREENSHOTS_DIR="$(cd "$SCRIPT_DIR/../screenshots" && pwd 2>/dev/null || echo "$SCRIPT_DIR/../screenshots")"
CONTAINER="windows"
RDP_HOST="127.0.0.1"
RDP_PORT=3389
RDP_USER="Docker"
RDP_PASS="admin"
RDP_SESSION="sketchup-link"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { echo "[win-screenshot] $*"; }
die()  { log "FATAL: $*"; exit 1; }

ensure_screenshots_dir() {
    mkdir -p "$SCREENSHOTS_DIR"
}

# ---------------------------------------------------------------------------
# QEMU screendump
# ---------------------------------------------------------------------------
qemu_screenshot() {
    local name="$1"
    local ts
    ts=$(date '+%Y%m%d_%H%M%S')
    local base="${name}_${ts}"
    local ppm_path="${SCREENSHOTS_DIR}/${base}.ppm"
    local png_path="${SCREENSHOTS_DIR}/${base}.png"

    ensure_screenshots_dir
    log "Taking QEMU screendump: $ppm_path"

    # Check QEMU monitor is accessible
    if ! docker exec "$CONTAINER" sh -c 'nc -z 127.0.0.1 7100 2>/dev/null' 2>/dev/null; then
        die "QEMU monitor (127.0.0.1:7100) not accessible inside container"
    fi

    # Send screendump command via netcat to QEMU HMP
    docker exec "$CONTAINER" sh -c '
        echo "screendump /tmp/screenshot.ppm" | timeout 10 nc 127.0.0.1 7100
    ' 2>/dev/null || true

    # Copy out of container
    if docker cp "${CONTAINER}:/tmp/screenshot.ppm" "$ppm_path" 2>/dev/null; then
        if [[ -f "$ppm_path" ]] && [[ -s "$ppm_path" ]]; then
            local size
            size=$(stat -c%s "$ppm_path" 2>/dev/null || stat -f%z "$ppm_path" 2>/dev/null || echo "0")
            log "  PPM captured: ${size} bytes"

            # Convert to PNG
            if command -v convert &>/dev/null; then
                convert "$ppm_path" "$png_path" 2>/dev/null && \
                    log "  PNG saved: $png_path ($(stat -c%s "$png_path" 2>/dev/null || stat -f%z "$png_path" 2>/dev/null) bytes)" || \
                    log "  WARNING: ImageMagick convert failed (installed?)"
            elif command -v ffmpeg &>/dev/null; then
                ffmpeg -y -i "$ppm_path" "$png_path" 2>/dev/null && \
                    log "  PNG saved (via ffmpeg): $png_path" || \
                    log "  WARNING: ffmpeg conversion failed"
            else
                log "  PPM saved (no converter available): $ppm_path"
            fi

            echo "$png_path"
            return 0
        fi
    fi

    # Fallback: try reading from inside container
    if docker exec "$CONTAINER" test -f /tmp/screenshot.ppm 2>/dev/null; then
        docker exec "$CONTAINER" cat /tmp/screenshot.ppm > "$ppm_path" 2>/dev/null
        if [[ -s "$ppm_path" ]]; then
            log "  PPM captured via cat fallback"
            if command -v convert &>/dev/null; then
                convert "$ppm_path" "$png_path" 2>/dev/null && echo "$png_path" || echo "$ppm_path"
            fi
            return 0
        fi
    fi

    die "Failed to capture QEMU screendump"
}

# ---------------------------------------------------------------------------
# RDP screenshot (agent-rdp)
# ---------------------------------------------------------------------------
rdp_screenshot() {
    local name="$1"
    local ts
    ts=$(date '+%Y%m%d_%H%M%S')
    local base="${name}_${ts}"
    local png_path="${SCREENSHOTS_DIR}/${base}.png"

    ensure_screenshots_dir
    log "Taking RDP screenshot: $png_path"

    # Check agent-rdp session
    if ! agent-rdp --session "$RDP_SESSION" session info &>/dev/null; then
        log "agent-rdp not connected — connecting..."
        agent-rdp --session "$RDP_SESSION" connect \
            --host "$RDP_HOST" \
            -u "$RDP_USER" \
            -p "$RDP_PASS" \
            --enable-win-automation \
            --drive "$SHARED_DIR:Shared" 2>&1 || \
            die "Failed to connect agent-rdp"
        sleep 2
    fi

    agent-rdp --session "$RDP_SESSION" screenshot -o "$png_path" 2>&1 || \
        die "Failed to take RDP screenshot"

    if [[ -f "$png_path" ]] && [[ -s "$png_path" ]]; then
        local size
        size=$(stat -c%s "$png_path" 2>/dev/null || stat -f%z "$png_path" 2>/dev/null || echo "0")
        log "  RDP screenshot: ${size} bytes"
        echo "$png_path"
        return 0
    fi

    die "RDP screenshot produced empty file"
}

# ---------------------------------------------------------------------------
# OCR locate (agent-rdp locate)
# ---------------------------------------------------------------------------
locate_text() {
    local text="$1"
    shift
    local action=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --action) action="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    log "Looking for text: '$text'"

    # Ensure connected via RDP
    if ! agent-rdp --session "$RDP_SESSION" session info &>/dev/null; then
        log "agent-rdp not connected — connecting..."
        agent-rdp --session "$RDP_SESSION" connect \
            --host "$RDP_HOST" \
            -u "$RDP_USER" \
            -p "$RDP_PASS" \
            --enable-win-automation \
            --drive "$SHARED_DIR:Shared" 2>&1 || \
            die "Failed to connect agent-rdp"
        sleep 2
    fi

    # Take screenshot first (for context)
    local ts
    ts=$(date '+%Y%m%d_%H%M%S')
    local screenshot_path="${SCREENSHOTS_DIR}/locate_${ts}.png"
    ensure_screenshots_dir
    agent-rdp --session "$RDP_SESSION" screenshot -o "$screenshot_path" 2>/dev/null || true

    # Run locate
    local locate_output
    locate_output=$(agent-rdp --session "$RDP_SESSION" locate "$text" --json 2>&1 || true)

    if echo "$locate_output" | grep -qi "Found.*line"; then
        log "$locate_output"
        echo "$locate_output"

        # Extract coordinates if action is click
        if [[ "$action" == "click" ]]; then
            local coords
            coords=$(echo "$locate_output" | grep -oP "click \d+ \d+" | head -1)
            if [[ -n "$coords" ]]; then
                log "Executing: agent-rdp mouse $coords"
                agent-rdp --session "$RDP_SESSION" mouse $coords 2>&1 || true
            fi
        fi

        return 0
    fi

    log "Text '$text' not found on screen"
    return 1
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if [[ $# -eq 0 ]]; then
    echo "Usage: win-screenshot.sh --qemu <name>    (PPM → PNG via QEMU screendump)"
    echo "       win-screenshot.sh --rdp <name>     (PNG via agent-rdp)"
    echo "       win-screenshot.sh --locate <text>  (OCR via agent-rdp locate)"
    echo "       win-screenshot.sh --locate <text> --action click"
    exit 0
fi

case "$1" in
    --qemu)
        if [[ $# -lt 2 ]]; then die "Missing screenshot name"; fi
        qemu_screenshot "$2"
        ;;
    --rdp)
        if [[ $# -lt 2 ]]; then die "Missing screenshot name"; fi
        rdp_screenshot "$2"
        ;;
    --locate)
        if [[ $# -lt 2 ]]; then die "Missing text to locate"; fi
        shift
        locate_text "$@"
        ;;
    *)
        die "Unknown mode: $1 (use --qemu, --rdp, or --locate)"
        ;;
esac
