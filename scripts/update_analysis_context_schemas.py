from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SRC = ROOT / "packages/grid-agent/src"
sys.path.insert(0, str(PACKAGE_SRC))

from grid_agent.analysis.models import AnalysisContext, AnalysisContextEvent  # noqa: E402


def main() -> None:
    schema_dir = ROOT / "schemas"
    _write_json_atomic(schema_dir / "analysis-context-v1.schema.json", AnalysisContext.model_json_schema())
    _write_json_atomic(
        schema_dir / "analysis-context-event-v1.schema.json",
        AnalysisContextEvent.model_json_schema(),
    )


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


if __name__ == "__main__":
    main()
