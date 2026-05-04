#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$(dirname "$0")/../compose.yml"
REPO_ROOT="$SCRIPT_DIR/../../../../../../"
PLUGIN_DIR="$SCRIPT_DIR/../.."
cd "$REPO_ROOT"

HOST="127.0.0.1"
PORT="9876"
MAX_WAIT=120
CONTAINER="windows"

# ---------------------------------------------------------------------------
# Step 0: Ensure Docker VM is running
# ---------------------------------------------------------------------------
# Check if the windows container is running (via docker compose ps)
if ! docker compose -f "$COMPOSE_FILE" ps "$CONTAINER" 2>/dev/null | grep -q "Up"; then
    echo "Container '$CONTAINER' is not running. Starting it now..."
    docker compose -f "$COMPOSE_FILE" up -d "$CONTAINER"
    echo "Waiting for container to become ready..."
    # Wait for the QEMU monitor port to be available inside the container
    for i in $(seq 1 120); do
        if docker compose -f "$COMPOSE_FILE" exec -T "$CONTAINER" sh -c 'nc -z 127.0.0.1 7100 2>/dev/null' 2>/dev/null; then
            echo "Container ready after ${i}s"
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
    echo "Container '$CONTAINER' is running"
fi

# ---------------------------------------------------------------------------
# Step 1: Launch SketchUp via QEMU HMP keystrokes
# ---------------------------------------------------------------------------
echo "=== Launching SketchUp in VM ==="
docker compose -f "$COMPOSE_FILE" exec -T "$CONTAINER" perl /shared/scripts/launch_sketchup.pl
echo "Keystrokes sent to QEMU monitor"

# ---------------------------------------------------------------------------
# Step 2: Wait for plugin HTTP server
# ---------------------------------------------------------------------------
echo "=== Waiting for plugin on ${HOST}:${PORT} ==="
for i in $(seq 1 "$MAX_WAIT"); do
    if curl -s --connect-timeout 2 "http://$HOST:$PORT/status" >/dev/null 2>&1; then
        echo "Plugin ready after ${i}s"
        break
    fi
    if [ "$i" -eq "$MAX_WAIT" ]; then
        echo "ERROR: Plugin did not start within ${MAX_WAIT}s"
        echo ""
        echo "Possible causes:"
        echo "  1. SketchUp may not be installed in the VM"
        echo "  2. The SketchUp Link plugin may not be installed in SketchUp"
        echo "  3. Port $PORT may not be forwarded to the VM (check compose.yml USER_PORTS)"
        echo "  4. Windows Firewall may be blocking port $PORT (add firewall rule or disable)"
        echo "  5. GPU issues inside the VM"
        echo ""
        echo "Debug commands:"
        echo "  docker compose -f $COMPOSE_FILE logs $CONTAINER --tail 50"
        echo "  curl http://127.0.0.1:$PORT/status"
        echo "  # RDP into the VM to check SketchUp state: make rdp-connect"
        exit 1
    fi
    sleep 1
done

# ---------------------------------------------------------------------------
# Step 3: Verify plugin has /screenshot endpoint
# ---------------------------------------------------------------------------
echo "=== Verifying plugin version ==="
HTTP_CHECK=$(curl -s -o /dev/null -w "%{http_code}" "http://$HOST:$PORT/screenshot")
if [ "$HTTP_CHECK" = "404" ]; then
    echo "ERROR: Plugin is outdated — missing /screenshot endpoint."
    echo "Rebuild and reinstall the plugin:"
    echo "  cd $PLUGIN_DIR && uv run -- ruby package.rb"
    echo "  Then copy sketchup-link-1.0.0.rbz contents to VM Extensions directory"
    exit 1
fi
echo "Plugin version OK (/screenshot returns HTTP $HTTP_CHECK)"

# ---------------------------------------------------------------------------
# Step 4: Create test model
# ---------------------------------------------------------------------------
echo "=== Creating test model ==="
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://$HOST:$PORT/test_model")
if [ "$HTTP_CODE" != "200" ]; then
    echo "ERROR: test model creation returned HTTP $HTTP_CODE"
    BODY=$(curl -s -X POST "http://$HOST:$PORT/test_model")
    echo "Response: $BODY"
    exit 1
fi
echo "Test model created (HTTP $HTTP_CODE)"

# ---------------------------------------------------------------------------
# Step 5: Run BDD screenshot tests
# ---------------------------------------------------------------------------
echo "=== Running BDD screenshot tests ==="
cd "$PLUGIN_DIR"
uv run pytest tests/bdd/ -v

echo "=== Done ==="
echo "Screenshots saved to: tests/bdd/screenshots/"
