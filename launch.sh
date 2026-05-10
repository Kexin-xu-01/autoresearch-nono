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

# Ensure nvm-managed node is in PATH (nvm is not sourced in non-interactive shells)
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh" --no-use

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTORESEARCH_DIR="$(realpath "${1:-$SCRIPT_DIR/workload}")"
# Check for IBD program bundle first, fall back to generic
if [[ -f "${AUTORESEARCH_DIR}/ibd/program_ibd.md.bundle" ]]; then
    BUNDLE="${AUTORESEARCH_DIR}/ibd/program_ibd.md.bundle"
else
    BUNDLE="${AUTORESEARCH_DIR}/climbmix/program.md.bundle"
fi

# Attestation check — required. Run must be aborted if program.md cannot be verified.
_verify() {
    local program_file="${BUNDLE%.bundle}"

    if [[ ! -f "${BUNDLE}" ]]; then
        echo "[nono] ABORT: no attestation bundle found at ${BUNDLE}."
        echo "[nono] Run the attestation setup steps in the README before launching."
        exit 1
    fi

    local verify_cmd="nono trust verify ${program_file}"

    if command -v gnome-keyring-daemon &>/dev/null; then
        result=$(dbus-run-session -- bash -c '
            echo "" | gnome-keyring-daemon --unlock --components=secrets &>/dev/null || true
            sleep 1
            nono trust verify '"${program_file}"' 2>&1
        ') && rc=0 || rc=$?
    else
        result=$($verify_cmd 2>&1) && rc=0 || rc=$?
    fi

    if [[ $rc -eq 0 ]]; then
        echo "[nono] Attestation OK."
    else
        echo "$result"
        echo "[nono] ABORT: attestation failed — program.md may have been tampered with."
        exit 1
    fi
}

echo "[nono] Checking attestation..."
_verify

echo "[nono] Starting agent under kernel enforcement..."
exec nono run \
    --profile claude-code-autoresearch \
    --allow-gpu \
    --allow-cwd \
    --workdir "${AUTORESEARCH_DIR}" \
    -- "$(dirname "$(command -v node)")/node" \
       "$(dirname "$(command -v node)")/../lib/node_modules/@anthropic-ai/claude-code/cli.js" \
       --dangerously-skip-permissions
