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
#   - trust policy + program.md signed (one-time, see README headless instructions)
#
set -euo pipefail

AUTORESEARCH_DIR="$(realpath "${1:?Usage: $0 <path-to-autoresearch-clone>}")"

# On servers (including those with a D-Bus socket but no keyring daemon),
# gnome-keyring must be started inside its own dbus-run-session to own the
# secrets service. We detect this by checking whether _NONO_KEYRING_READY is set,
# which we export after relaunching.
if [[ -z "${_NONO_KEYRING_READY:-}" ]] && command -v dbus-run-session &>/dev/null \
        && command -v gnome-keyring-daemon &>/dev/null; then
    echo "[nono] Starting keyring session..."
    export _NONO_KEYRING_READY=1
    exec dbus-run-session -- bash -c '
        echo "" | gnome-keyring-daemon --unlock --components=secrets &>/dev/null || true
        sleep 1
        exec bash '"$0"' '"$AUTORESEARCH_DIR"'
    '
fi

BUNDLE="${AUTORESEARCH_DIR}/program.md.bundle"

# Verify program.md has not been tampered with since signing
if [[ -f "${BUNDLE}" ]]; then
    echo "[nono] Verifying program.md attestation..."
    nono trust verify "${AUTORESEARCH_DIR}/program.md" || {
        echo "[nono] ABORT: program.md attestation failed."
        echo "[nono] Re-sign with:"
        echo "[nono]   dbus-run-session -- bash -c 'echo \"\" | gnome-keyring-daemon --unlock --components=secrets &>/dev/null; sleep 1 && nono trust sign --key default ${AUTORESEARCH_DIR}/program.md'"
        exit 1
    }
    echo "[nono] Attestation OK."
else
    echo "[nono] WARNING: No program.md.bundle found — running without attestation check."
    echo "[nono] See README (Headless quickstart) to enable attestation."
fi

echo "[nono] Starting agent under kernel enforcement..."
exec nono run \
    --profile autoresearch \
    --workdir "${AUTORESEARCH_DIR}" \
    -- claude
