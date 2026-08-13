from __future__ import annotations

import json
from pathlib import Path

from grid_agent.analysis.models import AnalysisContext, AnalysisContextEvent


def test_checked_in_schemas_match_pydantic_models() -> None:
    root = Path(__file__).resolve().parents[4]
    assert json.loads((root / "schemas/analysis-context-v1.schema.json").read_text()) == AnalysisContext.model_json_schema()
    assert (
        json.loads((root / "schemas/analysis-context-event-v1.schema.json").read_text())
        == AnalysisContextEvent.model_json_schema()
    )
