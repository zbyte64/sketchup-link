#!/usr/bin/env bash
# Ensure the host SSH keypair used to reach the VM exists, and that the committed
# public key matches it. Idempotent.
#
#   private key:  integration/shared/ssh/host_key       (generated, git-ignored)
#   public key:   integration/oem/authorized_keys.pub   (committed; installed into the VM)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
KEY_DIR="$ROOT/integration/shared/ssh"
KEY="$KEY_DIR/host_key"
COMMITTED_PUB="$ROOT/integration/oem/authorized_keys.pub"

mkdir -p "$KEY_DIR"
if [[ ! -f "$KEY" ]]; then
    ssh-keygen -t ed25519 -N '' -C 'sketchup-link-host' -f "$KEY" -q
    echo "generated $KEY"
fi
chmod 600 "$KEY"
ssh-keygen -y -f "$KEY" > "$KEY_DIR/host_key.pub"

if [[ ! -f "$COMMITTED_PUB" ]]; then
    cp "$KEY_DIR/host_key.pub" "$COMMITTED_PUB"
    echo "wrote $COMMITTED_PUB; commit it so provisioning installs this key"
elif ! diff -q "$KEY_DIR/host_key.pub" "$COMMITTED_PUB" >/dev/null; then
    echo "ERROR: $COMMITTED_PUB does not match the private key in $KEY" >&2
    echo "       rotate deliberately: replace the committed public key, then rebuild the VM." >&2
    exit 1
fi
echo "ssh key ok: $(cut -d' ' -f1,2 "$COMMITTED_PUB")"
