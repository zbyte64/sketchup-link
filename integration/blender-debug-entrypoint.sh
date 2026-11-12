#!/usr/bin/env bash
# Start the verification services for the Blender test containers, then keep the
# container alive. Every service is optional: a failure is logged and never stops the
# container, so a broken debug service cannot break the test path.
#
#   sshd        key-only SSH for the host (the same host key as the VM, under /root/.ssh)
#   Xvfb :99    a virtual X display so Blender's GUI can run headless-with-a-screen
#   x11vnc      a VNC view of that display on port 5900 (screenshot/inspect from the host)
set -u

log() { echo "[blender-debug] $*"; }

if [ -f /etc/ssh/ssh_host_ed25519_key ]; then
    mkdir -p /run/sshd
    /usr/sbin/sshd -D -e &
    log "sshd started on port 22"
else
    log "sshd skipped: no host key"
fi

export DISPLAY="${DISPLAY:-:99}"
if command -v Xvfb >/dev/null 2>&1; then
    Xvfb "$DISPLAY" -screen 0 1920x1080x24 -nolisten tcp &
    sleep 1
    log "Xvfb on $DISPLAY"
    if command -v x11vnc >/dev/null 2>&1; then
        x11vnc -display "$DISPLAY" -forever -shared -nopw -rfbport 5900 -quiet &
        log "x11vnc on port 5900"
    fi
fi

exec "$@"
