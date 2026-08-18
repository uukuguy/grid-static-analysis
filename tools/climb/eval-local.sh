#!/usr/bin/env bash
set -euo pipefail

ROOT=$(git rev-parse --show-toplevel)
SCORE=$(python3 "$ROOT/tools/capability_matrix.py" --json)

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
    "agent": [],
    "validation": [],
}
per_task = {}
for name, members in groups.items():
    values = [packages[item] for item in members if item in packages]
    per_task[name] = sum(values) / len(values) if values else 0.0
print(json.dumps({
    "total": score["coverage_percent"],
    "per_task": per_task,
    "release_ready": score["release_ready"],
    "published": score["published"],
    "total_in_scope": score["total_in_scope"],
}, ensure_ascii=False, sort_keys=True))
PY
