#!/usr/bin/env bash
# validate-vm.sh — Pre-flight validation before any test run.
#
# Runs 10 checks against the Windows VM environment and reports
# pass/fail for each. Exits 0 on all pass, 1 on any failure.
#
# Usage:
#   validate-vm.sh            # Run all checks
#   validate-vm.sh --quick    # Skip slower checks (shared folder write, RDP file)
#   validate-vm.sh --list     # List check names only
#   validate-vm.sh --check <n> # Run a specific check by number

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths & Config
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIN_EXEC="$SCRIPT_DIR/win-exec.sh"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
INTEGRATION_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VM_STORAGE="$INTEGRATION_DIR/vm-storage/data.img"
SHARED_DIR="$INTEGRATION_DIR/shared"
OEM_DIR="$INTEGRATION_DIR/oem"
CONTAINER="windows"
RDP_HOST="127.0.0.1"
RDP_PORT=3389

QUICK=false
HAS_FAILURE=false
CHECK_RESULTS=()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()    { echo -e "$*"; }
pass()   { log "  \e[32m✓ PASS\e[0m  $*"; CHECK_RESULTS+=("PASS:$*"); }
fail()   { log "  \e[31m✗ FAIL\e[0m  $*"; HAS_FAILURE=true; CHECK_RESULTS+=("FAIL:$*"); }
skip()   { log "  \e[33m- SKIP\e[0m  $*"; CHECK_RESULTS+=("SKIP:$*"); }
header() { log "\n\e[36m==>\e[0m \e[1m$*\e[0m"; }
die()    { log "  \e[31mERROR:\e[0m $*"; exit 1; }

# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

check_vm_storage() {
    header "Check 1: VM storage image"
    if [[ -f "$VM_STORAGE" ]]; then
        local size
        size=$(stat -c%s "$VM_STORAGE" 2>/dev/null || stat -f%z "$VM_STORAGE" 2>/dev/null || echo "0")
        local size_gb=$(( size / 1073741824 ))
        if [[ $size_gb -ge 10 ]]; then
            pass "data.img exists and is ${size_gb}GB (≥10GB)"
        else
            fail "data.img is only ${size_gb}GB (need ≥10GB)"
        fi
    else
        fail "data.img not found at $VM_STORAGE"
    fi
}

check_shared_dir() {
    header "Check 2: Shared directory structure"
    if [[ ! -d "$SHARED_DIR" ]]; then
        fail "Shared directory not found: $SHARED_DIR"
        return
    fi

    local missing=false
    for subdir in "scripts" "sketchup-link-extracted"; do
        if [[ -d "$SHARED_DIR/$subdir" ]]; then
            pass "Shared subdirectory: $subdir"
        else
            fail "Missing shared subdirectory: $subdir"
            missing=true
        fi
    done

    if [[ "$missing" == "false" ]]; then
        pass "All shared subdirectories present"
    fi
}

check_oem_dir() {
    header "Check 3: OEM directory"
    if [[ ! -d "$OEM_DIR" ]]; then
        fail "OEM directory not found: $OEM_DIR"
        return
    fi

    for f in "install.bat" "install_sketchup.ps1"; do
        if [[ -f "$OEM_DIR/$f" ]]; then
            pass "OEM file: $f"
        else
            fail "Missing OEM file: $f"
        fi
    done
}

check_container_running() {
    header "Check 4: Docker container running"
    if docker inspect "$CONTAINER" --format '{{.State.Status}}' 2>/dev/null | grep -q "running"; then
        local uptime
        uptime=$(docker inspect "$CONTAINER" --format '{{.State.StartedAt}}' 2>/dev/null || echo "unknown")
        pass "Container '$CONTAINER' is running (started: $uptime)"
    else
        fail "Container '$CONTAINER' is NOT running"
    fi
}

check_qemu_monitor() {
    header "Check 5: QEMU monitor port 7100"
    if docker exec "$CONTAINER" sh -c 'nc -z 127.0.0.1 7100 2>/dev/null' 2>/dev/null; then
        pass "QEMU monitor accessible on 127.0.0.1:7100 (inside container)"
    else
        fail "QEMU monitor not accessible on 127.0.0.1:7100"
    fi
}

check_rdp_port() {
    header "Check 6: RDP port 3389"
    if command -v nc &>/dev/null; then
        if nc -z "$RDP_HOST" "$RDP_PORT" 2>/dev/null; then
            pass "RDP port ${RDP_PORT} accessible from host"
        else
            fail "RDP port ${RDP_PORT} not accessible from host"
        fi
    else
        # Fallback: check docker port mapping
        if docker inspect "$CONTAINER" --format '{{range $p, $conf := .NetworkSettings.Ports}}{{if eq $p "3389/tcp"}}{{$conf}}{{end}}{{end}}' 2>/dev/null | grep -q "HostPort"; then
            pass "RDP port 3389 mapped in docker config"
        else
            fail "RDP port 3389 not mapped"
        fi
    fi
}

check_port_forwarding() {
    header "Check 7: Port 9876 forwarding"
    local found=false

    # Check docker-proxy
    if command -v ss &>/dev/null; then
        if ss -tlnp 2>/dev/null | grep -q ":9876"; then
            pass "Port 9876 listening on host via docker-proxy"
            found=true
        fi
    fi

    # Check iptables DNAT
    if docker exec "$CONTAINER" iptables -t nat -L PREROUTING 2>/dev/null | grep -q "9876" 2>/dev/null; then
        pass "iptables DNAT rule for 9876 found inside container"
        found=true
    fi

    # Check compose.yml USER_PORTS
    if docker inspect "$CONTAINER" --format '{{range $p, $conf := .NetworkSettings.Ports}}{{if eq $p "9876/tcp"}}{{$conf}}{{end}}{{end}}' 2>/dev/null | grep -q "HostPort"; then
        pass "Port 9876 mapped in docker config"
        found=true
    fi

    if [[ "$found" == "false" ]]; then
        fail "No port forwarding found for 9876"
    fi
}

check_samba() {
    header "Check 8: Samba running inside container"
    if docker exec "$CONTAINER" sh -c 'ps aux 2>/dev/null | grep -i "[s]mbd"' 2>/dev/null | grep -q .; then
        pass "Samba (smbd) is running inside container"
    else
        # Alternative: check if port 445 or 139 is open
        if docker exec "$CONTAINER" sh -c 'nc -z 127.0.0.1 445 2>/dev/null' 2>/dev/null; then
            pass "Samba port 445 is open"
        else
            fail "Samba not detected inside container"
        fi
    fi
}

check_shared_access() {
    header "Check 9: Shared folder accessible inside Windows"
    if [[ "$QUICK" == "true" ]]; then
        skip "Skipped (--quick mode)"
        return
    fi

    if [[ ! -x "$WIN_EXEC" ]]; then
        fail "win-exec.sh not available at $WIN_EXEC"
        return
    fi

    # Use win-exec to write a test file and verify it appears on host
    local test_marker="validate_vm_marker_$$"
    local host_test_file="$SHARED_DIR/.${test_marker}.txt"

    rm -f "$host_test_file"

    if "$WIN_EXEC" --timeout 60 \
        "cmd /c echo VALIDATION_OK > \"C:\\Users\\Docker\\Desktop\\Shared\\.${test_marker}.txt\" && type \"C:\\Users\\Docker\\Desktop\\Shared\\.${test_marker}.txt\"" \
        ".${test_marker}_out.txt" 2>/dev/null; then

        # Check if the file appeared on the host side
        if [[ -f "$host_test_file" ]]; then
            local content
            content=$(cat "$host_test_file" 2>/dev/null || echo "")
            if echo "$content" | grep -q "VALIDATION_OK"; then
                pass "Shared folder accessible: host sees file written from Windows"
                rm -f "$host_test_file"
                rm -f "$SHARED_DIR/.${test_marker}_out.txt" "$SHARED_DIR/.${test_marker}_out.txt.exitcode" 2>/dev/null || true
            else
                fail "Shared file content mismatch: got '$content'"
            fi
        else
            fail "File written from Windows not visible on host (shared folder mount issue?)"
            # Collect diagnostics
            "$WIN_EXEC" --no-connect --timeout 30 \
                "cmd /c dir C:\\Users\\Docker\\Desktop\\Shared" \
                ".${test_marker}_dir.txt" 2>/dev/null || true
            cat "$SHARED_DIR/.${test_marker}_dir.txt" 2>/dev/null || true
            rm -f "$SHARED_DIR/.${test_marker}_dir.txt" "$SHARED_DIR/.${test_marker}_dir.txt.exitcode" 2>/dev/null || true
        fi
    else
        fail "Failed to write test file via win-exec"
    fi

    # Cleanup
    rm -f "$host_test_file"
    rm -f "$SHARED_DIR/.${test_marker}_out.txt" "$SHARED_DIR/.${test_marker}_out.txt.exitcode" 2>/dev/null || true
}

check_agent_rdp() {
    header "Check 10: agent-rdp binary available"
    if command -v agent-rdp &>/dev/null; then
        local version
        version=$(agent-rdp --version 2>/dev/null || echo "available")
        pass "agent-rdp is available in PATH ($version)"
    elif npx agent-rdp --version &>/dev/null 2>&1; then
        local version
        version=$(npx agent-rdp --version 2>/dev/null || echo "available via npx")
        pass "agent-rdp is available via npx ($version)"
    else
        # Check common locations
        local found=false
        for loc in /usr/local/bin/agent-rdp ~/.npm/_npx/*/node_modules/@agent-rdp/*/bin/agent-rdp; do
            if [[ -x "$loc" ]]; then
                pass "agent-rdp found at $loc"
                found=true
                break
            fi
        done
        if [[ "$found" == "false" ]]; then
            fail "agent-rdp binary not found (try: npm install -g @agent-rdp/linux-x64)"
        fi
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║    Windows VM Pre-flight Validation          ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Parse args
LIST_ONLY=false
SPECIFIC_CHECK=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --quick)   QUICK=true; shift ;;
        --list)    LIST_ONLY=true; shift ;;
        --check)   SPECIFIC_CHECK="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: validate-vm.sh [--quick] [--list] [--check <n>]"
            echo ""
            echo "  --quick    Skip slower checks (shared folder write)"
            echo "  --list     List available checks"
            echo "  --check N  Run a specific check by number"
            exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

if [[ "$LIST_ONLY" == "true" ]]; then
    echo "Available checks:"
    echo "  1.  VM storage image (data.img exists, ≥10GB)"
    echo "  2.  Shared directory structure"
    echo "  3.  OEM directory (install.bat, install_sketchup.ps1)"
    echo "  4.  Docker container running"
    echo "  5.  QEMU monitor port 7100"
    echo "  6.  RDP port 3389"
    echo "  7.  Port 9876 forwarding"
    echo "  8.  Samba running"
    echo "  9.  Shared folder accessibility (write test)"
    echo "  10. agent-rdp binary availability"
    exit 0
fi

# Run checks
case "$SPECIFIC_CHECK" in
    1|"") check_vm_storage ;;
esac
case "$SPECIFIC_CHECK" in
    2|"") check_shared_dir ;;
esac
case "$SPECIFIC_CHECK" in
    3|"") check_oem_dir ;;
esac
case "$SPECIFIC_CHECK" in
    4|"") check_container_running ;;
esac
case "$SPECIFIC_CHECK" in
    5|"") check_qemu_monitor ;;
esac
case "$SPECIFIC_CHECK" in
    6|"") check_rdp_port ;;
esac
case "$SPECIFIC_CHECK" in
    7|"") check_port_forwarding ;;
esac
case "$SPECIFIC_CHECK" in
    8|"") check_samba ;;
esac
case "$SPECIFIC_CHECK" in
    9|"") check_shared_access ;;
esac
case "$SPECIFIC_CHECK" in
    10|"") check_agent_rdp ;;
esac

# Summary
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  Summary                                     ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

pass_count=0
fail_count=0
skip_count=0
for result in "${CHECK_RESULTS[@]}"; do
    case "$result" in
        PASS:*) pass_count=$(( pass_count + 1 )) ;;
        FAIL:*) fail_count=$(( fail_count + 1 )) ;;
        SKIP:*) skip_count=$(( skip_count + 1 )) ;;
    esac
done

log "  Passed: $pass_count"
log "  Failed: $fail_count"
[[ $skip_count -gt 0 ]] && log "  Skipped: $skip_count"
echo ""

if [[ "$HAS_FAILURE" == "true" ]]; then
    log "  \e[31mRESULT: FAIL — ${fail_count} check(s) failed\e[0m"
    log "  \e[33mAddress failures before proceeding with tests.\e[0m"
    exit 1
fi

log "  \e[32mRESULT: PASS — All checks passed\e[0m"
exit 0
