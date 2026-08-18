#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "docs/status/climb/runs.csv"
SESSION = ROOT / "docs/status/climb/session-state.json"
TARGET = 100.0


def main() -> int:
    current = None
    if RUNS.is_file():
        with RUNS.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                raw = row.get("local_score")
                if raw:
                    value = float(raw)
                    current = value if current is None else max(current, value)
    session = json.loads(SESSION.read_text(encoding="utf-8")) if SESSION.is_file() else {}
    release_closed = session.get("phase") == "complete"
    met = current is not None and current >= TARGET and release_closed
    print(json.dumps({
        "has_target": True,
        "metric": "local",
        "current": current,
        "target": TARGET,
        "met": met,
        "reason": (
            "release gate met"
            if met
            else "local score met; release closure pending"
            if current is not None and current >= TARGET
            else "continue capability implementation"
        ),
    }, sort_keys=True))
    return 10 if met else 0


if __name__ == "__main__":
    raise SystemExit(main())
