#!/usr/bin/env bash
set -euo pipefail

ROOT=$(git rev-parse --show-toplevel)
HYPOTHESIS_ID=${1:?usage: cycle.sh H-NNN}
RUN_DIR=$("$ROOT/tools/climb/train.sh" "$HYPOTHESIS_ID")
"$ROOT/tools/climb/eval-local.sh" "$RUN_DIR" >"$RUN_DIR/local-eval.json"
"$ROOT/tools/climb/decision-gate.py" --local-eval-json "$RUN_DIR/local-eval.json" >"$RUN_DIR/decision.json"
if [ "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["decision"])' "$RUN_DIR/decision.json")" = "PUSH" ]; then
  "$ROOT/tools/climb/push.sh" "$RUN_DIR" >"$RUN_DIR/push.json"
fi
"$ROOT/tools/climb/sync-cycle.py" \
  "$HYPOTHESIS_ID" \
  "$RUN_DIR" \
  "$RUN_DIR/local-eval.json" \
  "$RUN_DIR/decision.json"
printf '%s\n' "$RUN_DIR"
