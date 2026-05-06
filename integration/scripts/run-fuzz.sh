#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# run-fuzz.sh — Orchestrate fuzz testing against SketchUp VM.
#
# Usage:
#   ./integration/scripts/run-fuzz.sh              # Full mode (VM required)
#   ./integration/scripts/run-fuzz.sh --mock       # CI-safe mode (mock server)
#
# This script:
#   1. Ensures the Docker Windows VM is running (full mode only)
#   2. Creates the test model inside SketchUp
#   3. Runs the fuzz test suite
#   4. Collects artifacts into a timestamped report directory
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARTIFACT_DIR="$REPO_ROOT/tests/fuzz/artifacts/report_$(date +%Y%m%d_%H%M%S)"
MOCK_FLAG=""

# Parse args
if [[ "${1:-}" == "--mock" ]]; then
    MOCK_FLAG="--fuzz-mock"
    echo "[fuzz] CI-safe mode: running against Ruby mock server"
else
    echo "[fuzz] Full mode: running against SketchUp VM"
fi

# Ensure artifact base exists
mkdir -p "$ARTIFACT_DIR"

# Step 1: Ensure VM is running (full mode only)
if [[ -z "$MOCK_FLAG" ]]; then
    echo "[fuzz] Checking Docker VM status..."
    if ! docker compose -f "$REPO_ROOT/integration/compose.yml" ps --status running --format '{{.Name}}' 2>/dev/null | grep -q .; then
        echo "[fuzz] VM not running — starting..."
        docker compose -f "$REPO_ROOT/integration/compose.yml" up -d
        echo "[fuzz] Waiting for VM to be ready..."
        sleep 30  # Give Windows time to boot
    else
        echo "[fuzz] VM is already running."
    fi

    # Step 2: Create test model via SketchUp Link API
    echo "[fuzz] Creating test model in SketchUp..."
    # The test_model endpoint is served by the SketchUp Link plugin
    # when a model is open. POST /test_model creates the canonical test model.
    CREATE_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST http://127.0.0.1:9876/test_model 2>/dev/null || echo "000")
    if [[ "$CREATE_RESPONSE" != "200" ]]; then
        echo "[fuzz] WARNING: Could not create test model (HTTP $CREATE_RESPONSE)"
        echo "[fuzz] Proceeding anyway — existing model may be used."
    else
        echo "[fuzz] Test model created successfully."
    fi
fi

# Step 3: Run fuzz tests
echo "[fuzz] Running fuzz tests..."
cd "$REPO_ROOT"

if [[ -n "$MOCK_FLAG" ]]; then
    uv run pytest tests/fuzz/ -v --fuzz-mock 2>&1 | tee "$ARTIFACT_DIR/test_output.txt"
else
    uv run pytest tests/fuzz/ -v --fuzz-real 2>&1 | tee "$ARTIFACT_DIR/test_output.txt"
fi

EXIT_CODE=${PIPESTATUS[0]}

# Step 4: Collect artifacts
echo "[fuzz] Collecting artifacts..."
if [ -d "$REPO_ROOT/tests/fuzz/artifacts" ]; then
    # Move all per-test artifact directories into the report
    for d in "$REPO_ROOT"/tests/fuzz/artifacts/*/; do
        dirname="$(basename "$d")"
        # Skip the report directory itself
        if [[ "$dirname" != report_* ]]; then
            mv "$d" "$ARTIFACT_DIR/$dirname" 2>/dev/null || true
        fi
    done
fi

echo "[fuzz] Artifacts saved to: $ARTIFACT_DIR"
echo "[fuzz] Fuzz test suite exited with code $EXIT_CODE"
exit $EXIT_CODE
