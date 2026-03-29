#!/usr/bin/env bash
# launch.sh — run autoresearch under nono kernel-level enforcement
#
# Usage:
#   ./launch.sh <path-to-autoresearch-clone>
#
# Prerequisites:
#   - nono installed (https://github.com/lukehinds/nono)
#   - profile installed: cp profiles/autoresearch.json ~/.config/nono/profiles/
#   - program.md signed: nono trust sign --keyed <autoresearch>/program.md
#
set -euo pipefail

AUTORESEARCH_DIR="${1:?Usage: $0 <path-to-autoresearch-clone>}"
BUNDLE="${AUTORESEARCH_DIR}/program.md.bundle"

# Verify program.md has not been tampered with since signing
if [[ -f "${BUNDLE}" ]]; then
    echo "[nono] Verifying program.md attestation..."
    nono trust verify "${BUNDLE}" || {
        echo "[nono] ABORT: program.md attestation failed. Re-sign with: nono trust sign --keyed ${AUTORESEARCH_DIR}/program.md"
        exit 1
    }
    echo "[nono] Attestation OK."
else
    echo "[nono] WARNING: No program.md.bundle found at ${BUNDLE}"
    echo "[nono] To enable attestation: nono trust sign --keyed ${AUTORESEARCH_DIR}/program.md"
    echo "[nono] Proceeding without attestation check..."
fi

# Run agent under nono enforcement
exec nono run \
    --profile autoresearch \
    --workdir "${AUTORESEARCH_DIR}" \
    -- claude
