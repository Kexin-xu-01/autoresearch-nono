#!/usr/bin/env bash
# launch.sh — run autoresearch under nono kernel-level enforcement
#
# Usage:
#   ./launch.sh <path-to-autoresearch-clone>
#   ./launch.sh .   # if already in the repo directory
#
# Prerequisites:
#   - nono installed (https://github.com/lukehinds/nono)
#   - profile installed: cp profiles/autoresearch.json ~/.config/nono/profiles/
#   - program.md signed (see below)
#
# Signing on a headless server (no desktop keyring):
#   dbus-run-session -- bash -c \
#     'echo "" | gnome-keyring-daemon --unlock --components=secrets &>/dev/null & \
#      sleep 2 && nono trust keygen && nono trust sign --key default program.md'
#
set -euo pipefail

AUTORESEARCH_DIR="${1:?Usage: $0 <path-to-autoresearch-clone>}"
BUNDLE="${AUTORESEARCH_DIR}/program.md.bundle"

# Headless servers need a dbus session + gnome-keyring for the keystore.
# Wrap the whole script in dbus-run-session if DBUS_SESSION_BUS_ADDRESS is unset.
if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]] && command -v dbus-run-session &>/dev/null; then
    echo "[nono] No D-Bus session detected — relaunching under dbus-run-session..."
    exec dbus-run-session -- bash -c \
        'echo "" | gnome-keyring-daemon --unlock --components=secrets &>/dev/null; sleep 1; exec bash '"$0"' '"$AUTORESEARCH_DIR"
fi

# Verify program.md has not been tampered with since signing
if [[ -f "${BUNDLE}" ]]; then
    echo "[nono] Verifying program.md attestation..."
    nono trust verify "${BUNDLE}" || {
        echo "[nono] ABORT: program.md attestation failed."
        echo "[nono] Re-sign with:"
        echo "[nono]   dbus-run-session -- bash -c 'echo \"\" | gnome-keyring-daemon --unlock --components=secrets &>/dev/null; sleep 1 && nono trust sign --key default ${AUTORESEARCH_DIR}/program.md'"
        exit 1
    }
    echo "[nono] Attestation OK."
else
    echo "[nono] WARNING: No program.md.bundle found at ${BUNDLE}"
    echo "[nono] To enable attestation (headless):"
    echo "[nono]   dbus-run-session -- bash -c 'echo \"\" | gnome-keyring-daemon --unlock --components=secrets &>/dev/null; sleep 1 && nono trust keygen && nono trust sign --key default ${AUTORESEARCH_DIR}/program.md'"
    echo "[nono] Proceeding without attestation check..."
fi

# Run agent under nono enforcement
exec nono run \
    --profile autoresearch \
    --workdir "${AUTORESEARCH_DIR}" \
    -- claude
