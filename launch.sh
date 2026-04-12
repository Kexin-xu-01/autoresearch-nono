#!/usr/bin/env bash
# launch.sh — run autoresearch under nono kernel-level enforcement
#
# Usage:
#   ./launch.sh <path-to-autoresearch-clone>
#   ./launch.sh .   # if already in the repo directory
#
# Prerequisites:
#   - nono installed (https://github.com/lukehinds/nono)
#   - profile installed: cp profiles/claude-code-autoresearch.json ~/.config/nono/profiles/
#
set -euo pipefail

AUTORESEARCH_DIR="$(realpath "${1:?Usage: $0 <path-to-autoresearch-clone>}")"
BUNDLE="${AUTORESEARCH_DIR}/program.md.bundle"

# Attestation check (optional — requires persistent keyring, see README).
# Skipped automatically if no bundle exists or if running on a headless server
# where the keyring cannot persist between sessions (JupyterHub, cloud VMs).
_try_verify() {
    if [[ ! -f "${BUNDLE}" ]]; then
        echo "[nono] No program.md.bundle found — skipping attestation."
        echo "[nono] See README to enable attestation on a desktop system."
        return 0
    fi

    local verify_cmd="nono trust verify ${AUTORESEARCH_DIR}/program.md"

    # Try verification. If keyring is unavailable, warn and continue rather than abort.
    if command -v gnome-keyring-daemon &>/dev/null; then
        result=$(dbus-run-session -- bash -c '
            echo "" | gnome-keyring-daemon --unlock --components=secrets &>/dev/null || true
            sleep 1
            nono trust verify '"${AUTORESEARCH_DIR}/program.md"' 2>&1
        ') && rc=0 || rc=$?
    else
        result=$($verify_cmd 2>&1) && rc=0 || rc=$?
    fi

    if [[ $rc -eq 0 ]]; then
        echo "[nono] Attestation OK."
    else
        if echo "$result" | grep -q "ECDSA signature\|keystore\|Secret Service\|unlock prompt"; then
            echo "[nono] WARNING: Attestation skipped — keyring not available in this environment."
            echo "[nono] Kernel sandbox enforcement is still active."
        else
            echo "$result"
            echo "[nono] ABORT: program.md attestation failed (tampering detected)."
            exit 1
        fi
    fi
}

echo "[nono] Checking attestation..."
_try_verify

echo "[nono] Starting agent under kernel enforcement..."
exec nono run \
    --profile claude-code-autoresearch \
    --allow-gpu \
    --allow-cwd \
    --workdir "${AUTORESEARCH_DIR}" \
    -- claude
