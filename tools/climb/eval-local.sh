#!/usr/bin/env bash
set -euo pipefail

ROOT=$(git rev-parse --show-toplevel)
SCORE=$(python3 "$ROOT/tools/capability_matrix.py" --json)
mkdir -p "$ROOT/runs/climb"
if [ "$#" -ge 1 ]; then
  RUN_DIR=$1
  mkdir -p "$RUN_DIR"
else
  RUN_DIR=$(mktemp -d "$ROOT/runs/climb/eval-XXXXXX")
fi

uv run --project "$ROOT/packages/grid-simulator" pytest -q \
  "$ROOT/packages/grid-simulator/tests/test_capability_materialization.py" >/dev/null
uv run --project "$ROOT/packages/grid-agent" pytest -q \
  "$ROOT/packages/grid-agent/tests/tools/test_catalog.py" \
  "$ROOT/packages/grid-agent/tests/analysis/test_projector.py::test_projector_tracks_equivalent_child_context_and_replay_idempotently" \
  "$ROOT/packages/grid-agent/tests/contract/test_skill.py" >/dev/null
npm test --prefix "$ROOT/packages/pi-grid-tools" -- \
  --test-name-pattern='registers catalog tools|newly published static-analysis tools' >/dev/null
uv run --project "$ROOT/packages/grid-agent" pytest -q \
  "$ROOT/packages/grid-agent/tests/validation/test_corpus.py" \
  "$ROOT/packages/grid-agent/tests/validation/test_case_contract.py" >/dev/null
uv run --project "$ROOT/packages/grid-agent" python "$ROOT/validation/run.py" \
  --mode scripted-pi \
  --suite static-analysis-full \
  --report "$RUN_DIR/validation-static-analysis-full.json" \
  --timeout-seconds 120

if [ "${CLIMB_FULL_GATE:-0}" = "1" ]; then
  make -C "$ROOT" test >/dev/null
  make -C "$ROOT" test-e2e >/dev/null
fi

python3 - "$SCORE" <<'PY'
import json
import sys

score = json.loads(sys.argv[1])
packages = score["per_package"]
groups = {
    "model": ["model-lifecycle", "topology"],
    "data": ["model-data"],
    "analyses": ["power-flow", "opf", "short-circuit", "state-estimation", "diagnostic", "contingency", "policy-risk", "protection"],
    "results": ["result-analysis", "evidence"],
    "agent": ["__verified__"],
    "validation": ["__verified__"],
}
per_task = {}
for name, members in groups.items():
    values = [100.0 if item == "__verified__" else packages[item] for item in members if item == "__verified__" or item in packages]
    per_task[name] = sum(values) / len(values) if values else 0.0
total = sum(per_task.values()) / len(per_task)
release_ready = score["release_ready"] and all(value == 100.0 for value in per_task.values())
print(json.dumps({
    "total": total,
    "per_task": per_task,
    "release_ready": release_ready,
    "published": score["published"],
    "total_in_scope": score["total_in_scope"],
}, ensure_ascii=False, sort_keys=True))
PY
