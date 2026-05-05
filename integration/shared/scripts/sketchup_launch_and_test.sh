#!/usr/bin/env bash
# sketchup_launch_and_test.sh — Full-pipeline orchestrator for
# `make test-bdd-sketchup`.
#
# Phases:
#   1. Build plugin and extract to shared/
#   2. Ensure Docker VM is running
#   3. Wait for SketchUp + plugin (launch via QEMU kbd if needed)
#   4. Verify /screenshot endpoint and create test model
#   5. Build and start Blender container
#   6. Run TCP-mode BDD tests with screenshot capture
#   7. Report results
set -euo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/../../compose.yml"
PLUGIN_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"

HOST="127.0.0.1"
PORT="9876"
MAX_WAIT=120
CONTAINER="windows"
SHARED_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
EXTRACT_DIR="$SHARED_DIR/sketchup-link-extracted"
SCREENSHOTS_HOST_DIR="$(cd "$PLUGIN_DIR/tests/bdd/screenshots" && pwd 2>/dev/null || echo "$PLUGIN_DIR/tests/bdd/screenshots")"

echo "=== Paths ==="
echo "  Script dir:     $SCRIPT_DIR"
echo "  Compose file:   $COMPOSE_FILE"
echo "  Plugin dir:     $PLUGIN_DIR"
echo "  Shared dir:     $SHARED_DIR"
echo "  Extract dir:    $EXTRACT_DIR"
echo "  Screenshots:    $SCREENSHOTS_HOST_DIR"

# ---------------------------------------------------------------------------
# Phase 1: Build plugin and extract to shared/
# ---------------------------------------------------------------------------
echo ""
echo "=== Phase 1: Build and extract plugin ==="
mkdir -p "$EXTRACT_DIR"

# Determine the latest built .rbz
RBZ_FILE="$PLUGIN_DIR/dist/sketchup-link-1.0.0.rbz"
NEED_BUILD=false
if [ ! -f "$RBZ_FILE" ]; then
    NEED_BUILD=true
else
    # Rebuild if any source file is newer than the .rbz
    NEWEST_SRC=$(find "$PLUGIN_DIR/sketchup_link" "$PLUGIN_DIR/sketchup_link.rb" -type f -newer "$RBZ_FILE" 2>/dev/null | head -1)
    if [ -n "$NEWEST_SRC" ]; then
        NEED_BUILD=true
    fi
fi

if [ "$NEED_BUILD" = true ]; then
    echo "Building plugin .rbz..."
    mkdir -p "$PLUGIN_DIR/dist"
    ORIG_DIR="$PWD"
    cd "$PLUGIN_DIR"
    bundle exec ruby package.rb
    cd "$ORIG_DIR"
    echo "  Plugin built: $RBZ_FILE"
else
    echo "  Plugin .rbz is up-to-date, skipping build"
fi

# Extract (if needed)
if [ -f "$RBZ_FILE" ]; then
    echo "Extracting plugin to $EXTRACT_DIR..."
    # unzip -o overwrites, -q quiet, -d target
    unzip -q -o "$RBZ_FILE" -d "$EXTRACT_DIR"
    echo "  Extracted: $(find "$EXTRACT_DIR" -type f | wc -l) files"
    echo "  Entry point: $EXTRACT_DIR/sketchup_link.rb"
else
    echo "WARNING: $RBZ_FILE not found after build step"
fi

# ---------------------------------------------------------------------------
# Phase 2: Ensure Docker VM is running
# ---------------------------------------------------------------------------
echo ""
echo "=== Phase 2: Ensure Docker VM is running ==="
if ! docker inspect "$CONTAINER" --format '{{.State.Status}}' 2>/dev/null | grep -q "running"; then
    echo "Container '$CONTAINER' is not running. Starting..."
    docker start "$CONTAINER" >/dev/null 2>&1 || docker compose -f "$COMPOSE_FILE" up -d "$CONTAINER"
    echo "Waiting for container to become ready..."
    for i in $(seq 1 120); do
        if docker exec "$CONTAINER" sh -c 'nc -z 127.0.0.1 7100 2>/dev/null' 2>/dev/null; then
            echo "  Container ready after ${i}s"
            break
        fi
        if [ "$i" -eq 120 ]; then
            echo "ERROR: Container did not become ready within 120s"
            echo "Check logs: docker compose -f $COMPOSE_FILE logs $CONTAINER"
            exit 1
        fi
        sleep 1
    done
else
    echo "  Container '$CONTAINER' is already running"
fi

LOG_FILE="$SHARED_DIR/install_sketchup.log"
echo "  Checking SketchUp installation log..."
if [ -f "$LOG_FILE" ]; then
    echo ""
    echo "  === Installation log ($LOG_FILE) ==="
    cat "$LOG_FILE"
    echo "  === End of log ==="
    echo ""

    SUCCESS=false
    HAS_ERROR=false

    if grep -q "SketchUp installation complete" "$LOG_FILE"; then
        SUCCESS=true
    fi

    if grep -q "ERROR" "$LOG_FILE"; then
        HAS_ERROR=true
    fi

    if [ "$SUCCESS" = true ] && [ "$HAS_ERROR" = false ]; then
        echo "  Installation result: SUCCESS"
    elif [ "$SUCCESS" = true ] && [ "$HAS_ERROR" = true ]; then
        echo "  WARNING: Installation completed BUT errors were logged — review above"
    elif [ "$SUCCESS" = false ] && [ "$HAS_ERROR" = true ]; then
        echo "  WARNING: Installation FAILED with errors — review above"
    else
        echo "  WARNING: Installation did not reach completion — review above"
    fi
else
    echo "  WARNING: Installation log not found at $LOG_FILE"
    echo "           (install_sketchup.ps1 may not have completed yet,"
    echo "            or the shared volume mount may not be accessible)"
fi

# ---------------------------------------------------------------------------
# Phase 3: Wait for SketchUp + plugin server
# ---------------------------------------------------------------------------
echo ""
echo "=== Phase 3: Wait for SketchUp + plugin ==="
PLUGIN_READY=false

# First polling window: just check (SketchUp might already be running)
echo "  Checking for plugin at ${HOST}:${PORT}..."
for i in $(seq 1 60); do
    if curl -s --connect-timeout 2 "http://$HOST:$PORT/status" >/dev/null 2>&1; then
        echo "  Plugin ready after ${i}s (already running)"
        PLUGIN_READY=true
        break
    fi
    sleep 1
done

# If not ready after 60s, try launching SketchUp via QEMU keystrokes
if [ "$PLUGIN_READY" = false ]; then
    echo "  Plugin not responding after 60s — attempting to launch SketchUp..."
    docker exec "$CONTAINER" perl /shared/scripts/launch_sketchup.pl
    echo "  Keystrokes sent, continuing to poll..."

    # Second polling window (another 60s)
    for i in $(seq 1 60); do
        if curl -s --connect-timeout 2 "http://$HOST:$PORT/status" >/dev/null 2>&1; then
            echo "  Plugin ready after $((60 + i))s"
            PLUGIN_READY=true
            break
        fi
        if [ "$i" -eq 60 ]; then
            echo "ERROR: Plugin did not start within ${MAX_WAIT}s total"
            echo ""
            echo "Possible causes:"
            echo "  1. SketchUp may not be installed in the VM (check OEM installation)"
            echo "  2. The SketchUp Link plugin may not be installed (check shared/sketchup-link-extracted/)"
            echo "  3. Port $PORT may not be forwarded (check compose.yml USER_PORTS)"
            echo "  4. Windows Firewall (check if install.bat ran)"
            echo "  5. GPU issues inside the VM"
            echo ""
            echo "Diagnostic commands:"
            echo "  docker compose -f $COMPOSE_FILE logs $CONTAINER --tail 50"
            echo "  docker compose -f $COMPOSE_FILE exec -T $CONTAINER cmd /c 'echo OEM scripts status'"
            echo "  curl http://127.0.0.1:$PORT/status"
            echo "  # RDP into VM: make rdp-connect (or use any RDP client to localhost:3389)"
            exit 1
        fi
        sleep 1
    done
fi

# ---------------------------------------------------------------------------
# Phase 4: Verify /screenshot endpoint + create test model
# ---------------------------------------------------------------------------
echo ""
echo "=== Phase 4: Verify endpoint + create test model ==="

echo "  Checking /screenshot endpoint..."
HTTP_CHECK=$(curl -s -o /dev/null -w "%{http_code}" "http://$HOST:$PORT/screenshot")
if [ "$HTTP_CHECK" = "404" ]; then
    echo "ERROR: Plugin is outdated — missing /screenshot endpoint."
    echo "  Rebuild the plugin and re-install in the VM:"
    echo "    cd $PLUGIN_DIR && ruby package.rb"
    echo "    Then re-extract to $EXTRACT_DIR"
    exit 1
fi
echo "  /screenshot returns HTTP $HTTP_CHECK (OK)"

echo "  Creating test model..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://$HOST:$PORT/test_model")
if [ "$HTTP_CODE" != "200" ]; then
    echo "ERROR: test model creation returned HTTP $HTTP_CODE"
    BODY=$(curl -s -X POST "http://$HOST:$PORT/test_model")
    echo "  Response: $BODY"
    exit 1
fi
echo "  Test model created (HTTP $HTTP_CODE)"

# ---------------------------------------------------------------------------
# Phase 5: Build and start Blender container
# ---------------------------------------------------------------------------
echo ""
echo "=== Phase 5: Build and start Blender container ==="

echo "  Building Blender image..."
docker compose -f "$COMPOSE_FILE" build blender
echo "  Build complete"

echo "  Starting Blender container..."
docker compose -f "$COMPOSE_FILE" up -d blender

# Wait for Blender container to be running
for i in $(seq 1 30); do
    STATUS=$(docker container inspect -f '{{.State.Status}}' blender 2>/dev/null || echo "missing")
    if [ "$STATUS" = "running" ]; then
        echo "  Blender container running after ${i}s"
        break
    fi
    if [ "$STATUS" = "exited" ]; then
        echo "WARNING: Blender container exited immediately. Logs:"
        docker compose -f "$COMPOSE_FILE" logs blender --tail 20
        # Not fatal — tests will handle missing Blender gracefully
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "WARNING: Blender container did not reach 'running' state within 30s"
        echo "  Current status: $STATUS"
        docker compose -f "$COMPOSE_FILE" logs blender --tail 10
    fi
    sleep 1
done

# Ensure screenshots directory exists on host (shared volume mount target)
mkdir -p "$SCREENSHOTS_HOST_DIR"

# ---------------------------------------------------------------------------
# Phase 6: Run TCP-mode BDD tests
# ---------------------------------------------------------------------------
echo ""
echo "=== Phase 6: Run TCP-mode BDD tests ==="

cd "$PLUGIN_DIR"

# Explicit file list guarantees only TCP-mode tests run (no Unix-socket tests
# that would fail without a Ruby mock server).
set +e  # Don't exit on test failure — we want to report results
uv run pytest \
    tests/bdd/test_live_sync_tcp_scenarios.py \
    tests/bdd/test_geometry_fidelity_tcp_scenarios.py \
    -v \
    --tb=short
TEST_EXIT=$?
set -e

# ---------------------------------------------------------------------------
# Phase 7: Report
# ---------------------------------------------------------------------------
echo ""
echo "=== Phase 7: Results ==="

if [ "$TEST_EXIT" -eq 0 ]; then
    echo "SUCCESS: All TCP-mode BDD tests passed."
else
    echo "FAILURE: Some TCP-mode BDD tests failed (exit code $TEST_EXIT)."
fi

echo ""
echo "Screenshot locations:"
echo "  Host directory: $SCREENSHOTS_HOST_DIR/<scenario_name>/"
echo ""
echo "  Per scenario:"
for scenario_dir in "$SCREENSHOTS_HOST_DIR"/*/; do
    if [ -d "$scenario_dir" ]; then
        name=$(basename "$scenario_dir")
        echo "    $name:"
        for f in "$scenario_dir"/*.png "$scenario_dir"/*.txt; do
            [ -f "$f" ] && echo "      $(basename "$f")"
        done
    fi
done

echo ""
echo "=== Done (exit $TEST_EXIT) ==="
exit "$TEST_EXIT"
