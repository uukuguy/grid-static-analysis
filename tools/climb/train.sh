#!/usr/bin/env bash
set -euo pipefail

ROOT=$(git rev-parse --show-toplevel)
HYPOTHESIS_ID=${1:?usage: train.sh H-NNN}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOWER_HYPOTHESIS_ID=$(printf '%s' "$HYPOTHESIS_ID" | tr '[:upper:]' '[:lower:]')
RUN_DIR="$ROOT/runs/climb/${STAMP}-${LOWER_HYPOTHESIS_ID}"
mkdir -p "$RUN_DIR"
python3 - "$RUN_DIR/manifest.json" "$HYPOTHESIS_ID" "$STAMP" <<'PY'
import json
import sys
from pathlib import Path

Path(sys.argv[1]).write_text(json.dumps({
    "hypothesis_id": sys.argv[2],
    "started_at": sys.argv[3],
    "kind": "static-analysis-capability-gate",
}, sort_keys=True) + "\n")
PY
printf '%s\n' "$RUN_DIR"
