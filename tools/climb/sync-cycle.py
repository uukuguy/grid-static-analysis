#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "docs/status/climb"
SUBSCORES = ("model", "data", "analyses", "results", "agent", "validation")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("hypothesis_id")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("eval_json", type=Path)
    parser.add_argument("decision_json", type=Path)
    args = parser.parse_args()

    hypotheses_path = STATE / "hypotheses.yaml"
    document = json.loads(hypotheses_path.read_text(encoding="utf-8"))
    hypotheses = document["hypotheses"]
    known = {item["id"]: item for item in hypotheses}
    if args.hypothesis_id not in known:
        raise SystemExit(f"unknown hypothesis: {args.hypothesis_id}")
    score = json.loads(args.eval_json.read_text(encoding="utf-8"))
    decision = json.loads(args.decision_json.read_text(encoding="utf-8"))
    if not score.get("release_ready") or decision.get("decision") != "PUSH":
        status = "falsified"
        verdict = str(decision.get("reason", "local release gate failed"))
    else:
        status = "confirmed"
        verdict = "confirmed: deterministic local release gate passed"

    now = datetime.now(timezone.utc).astimezone()
    run_id = args.run_dir.name
    events = list(document.get("events", []))
    if any(event.get("run_id") == run_id for event in events):
        raise SystemExit(f"run already synchronized: {run_id}")
    events.append(
        {
            "hypothesis_id": args.hypothesis_id,
            "run_id": run_id,
            "status": status,
            "recorded_at": now.isoformat(timespec="seconds"),
            "local_score": score["total"],
            "per_task": score["per_task"],
            "verdict": verdict,
        }
    )
    document["events"] = events
    hypotheses_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    runs_path = STATE / "runs.csv"
    with runs_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if any(row["run_id"] == run_id for row in rows):
        raise SystemExit(f"run already recorded: {run_id}")
    cycle = max((int(row["cycle"]) for row in rows), default=0) + 1
    row = {
        "run_id": run_id,
        "cycle": cycle,
        "session": "2026-08-18-full-capability",
        "hypothesis_id": args.hypothesis_id,
        "paradigm": known[args.hypothesis_id]["parent_paradigm"],
        "parent_run": rows[-1]["run_id"] if rows else "",
        "pushed_at": now.isoformat(timespec="seconds"),
        "lb_landed_at": now.isoformat(timespec="seconds"),
        "local_score": score["total"],
        **{f"local_{name}": score["per_task"][name] for name in SUBSCORES},
        "online_score": score["total"],
        "gap": 0.0,
        "push_decision": decision["decision"],
        "decision_reason": decision["reason"],
        "verdict": verdict,
        "train_cost_h": 0.0,
        "manifest_path": str((args.run_dir / "manifest.json").relative_to(ROOT)),
    }
    with runs_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]) if rows else list(row),
            lineterminator="\n",
        )
        writer.writerow({key: row.get(key, "") for key in writer.fieldnames})

    effective = {item["id"]: item["status"] for item in hypotheses}
    for event in events:
        effective[event["hypothesis_id"]] = event["status"]
    remaining = [item["id"] for item in hypotheses if effective[item["id"]] in {"pending", "in-flight"}]
    session = json.loads((STATE / "session-state.json").read_text(encoding="utf-8"))
    session.update(
        {
            "phase": "release closure" if not remaining else f"{remaining[0]} implementation",
            "last_cycle": cycle,
            "next_hypothesis": remaining[0] if remaining else "none",
            "in_flight": None,
            "next_action": (
                "Run complete release verification and provider semantic acceptance."
                if not remaining
                else f"Execute {remaining[0]} through the deterministic local gate."
            ),
        }
    )
    (STATE / "session-state.json").write_text(json.dumps(session, ensure_ascii=False) + "\n", encoding="utf-8")

    with (STATE / "adjudicator-log.md").open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n## Cycle {cycle} — {args.hypothesis_id}\n\n"
            f"- Verdict: {status.upper()}.\n"
            f"- Local score: {score['total']:.2f}; subscores: {json.dumps(score['per_task'], sort_keys=True)}.\n"
            f"- Decision: {decision['decision']} — {decision['reason']}.\n"
        )
    with (ROOT / "docs/status/JOURNAL.md").open("a", encoding="utf-8") as handle:
        handle.write(
            f"- {now:%H:%M} climb {args.hypothesis_id} {status}，本地门 {score['total']:.0f}% [{run_id}]\n"
        )
    subprocess.run([str(ROOT / "tools/climb/regen-tree.py")], check=True)
    target = subprocess.run([str(ROOT / "tools/climb/check-target.py")], check=False)
    return 0 if target.returncode in {0, 10} else target.returncode


if __name__ == "__main__":
    raise SystemExit(main())
