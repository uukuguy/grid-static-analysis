#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "docs/status/climb"


def main() -> None:
    hypotheses = json.loads((STATE / "hypotheses.yaml").read_text(encoding="utf-8"))["hypotheses"]
    hypothesis_document = json.loads((STATE / "hypotheses.yaml").read_text(encoding="utf-8"))
    effective_status = {item["id"]: item["status"] for item in hypotheses}
    for event in hypothesis_document.get("events", []):
        effective_status[event["hypothesis_id"]] = event["status"]
    session = json.loads((STATE / "session-state.json").read_text(encoding="utf-8"))
    with (STATE / "runs.csv").open(newline="", encoding="utf-8") as handle:
        runs = list(csv.DictReader(handle))
    active = [item for item in hypotheses if effective_status[item["id"]] in {"pending", "in-flight"}]
    confirmed = [item for item in hypotheses if effective_status[item["id"]] == "confirmed"]
    falsified = [item for item in hypotheses if effective_status[item["id"]] == "falsified"]
    tree = {
        "schema_version": 1,
        "generated_from_runs": len(runs),
        "active": [item["id"] for item in active],
        "confirmed": [item["id"] for item in confirmed],
        "falsified": [item["id"] for item in falsified],
    }
    (STATE / "research-tree.json").write_text(json.dumps(tree, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Research Tree — pandapower static-analysis full capability",
        "",
        f"> Generated deterministically from {len(runs)} climb runs.",
        "",
        "**Target:** 100% of in-scope matrix rows and all release gates.",
        "",
        "## In-flight",
        "",
        f"- Phase: {session.get('phase', 'unknown')}",
        f"- Last cycle: {session.get('last_cycle', 0)}",
        f"- Next hypothesis: {session.get('next_hypothesis', 'none')}",
        f"- Next action: {session.get('next_action', 'none')}",
        "",
        "## Runs",
        "",
    ]
    if runs:
        lines.extend(
            f"- {row['run_id']}: {row['local_score']}% — {row['verdict']}"
            for row in runs
        )
    else:
        lines.append("- No scored cycle yet.")
    lines.extend(["", "## Active hypotheses", ""])
    lines.extend(f"- **{item['id']}**: {item['description']}" for item in active)
    lines.extend(["", "## Confirmed", ""])
    if confirmed:
        lines.extend(f"- **{item['id']}**: {item['description']}" for item in confirmed)
    else:
        lines.append("- None.")
    lines.extend(["", "## Negative cache", ""])
    lines.extend(f"- {item}" for item in session.get("falsified_routes", []))
    (STATE / "research-tree.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
