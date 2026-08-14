"""Immutable acceptance check for the historical v0.2 trajectory run."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/grid-agent/src"))

from grid_agent.trajectory.canonical import canonical_json_bytes  # noqa: E402
from grid_agent.trajectory.legacy_v02 import LegacyV02Importer  # noqa: E402
from grid_agent.trajectory.service import ProjectionService  # noqa: E402


CONTRACT = ROOT / "packages/grid-agent/tests/fixtures/trajectory/v02-golden-contract.json"


def tree_digests(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(root.rglob("*")) if path.is_file()}


def validate(run_root: Path) -> dict[str, object]:
    before = tree_digests(run_root)
    projected = ProjectionService(run_root.parents[1] / ".grid-agent/trajectory-cache").open_run(run_root)
    replay = LegacyV02Importer(run_root).import_run()
    after = tree_digests(run_root)
    starts = [event for event in replay.events if event.event_type == "tool.started"]
    results = [event for event in replay.events if event.event_type == "tool.completed"]
    paired = len({event.scope.tool_call_id for event in starts} & {event.scope.tool_call_id for event in results})
    q7 = next((problem for problem in projected.business.problems if problem.turn_id.endswith("-t007")), None)
    q7_ok = bool(q7 and any(node.kind == "verified-result" for node in q7.nodes))
    digests = {name: hashlib.sha256(canonical_json_bytes(value.model_dump(mode="json"))).hexdigest() for name, value in {"agent": projected.agent, "business": projected.business, "context": projected.context, "artifacts": projected.artifacts}.items()}
    source_digest = hashlib.sha256(canonical_json_bytes(before)).hexdigest()
    return {"analysis_id": projected.analysis_id, "source_unchanged": before == after, "source_digest": source_digest, "turn_count": len(projected.agent.turns), "tool_start_count": len(starts), "tool_result_count": len(results), "paired_tool_count": paired, "q7_lineage_verified": q7_ok, "projection_digests": digests}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--update-contract", action="store_true")
    args = parser.parse_args()
    summary = validate(args.run_root)
    print(json.dumps(summary, sort_keys=True, ensure_ascii=False))
    if args.update_contract:
        return 0
    try:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("golden contract is unavailable", file=sys.stderr)
        return 1
    expected = {key: contract.get(key) for key in summary}
    required = summary["source_unchanged"] and (summary["turn_count"], summary["tool_start_count"], summary["tool_result_count"], summary["paired_tool_count"], summary["q7_lineage_verified"]) == (9, 36, 36, 36, True)
    return 0 if required and expected == summary else 1


if __name__ == "__main__":
    raise SystemExit(main())
