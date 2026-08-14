from __future__ import annotations

import json
from pathlib import Path

from grid_agent.trajectory.events import RunEvent


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "schemas/grid-run-event-v1.schema.json"
    path.write_text(
        json.dumps(RunEvent.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
