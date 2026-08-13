from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

from grid_agent.analysis.models import AnalysisContext, AnalysisContextEvent, EventType


def test_checked_in_schemas_match_pydantic_models() -> None:
    root = Path(__file__).resolve().parents[4]
    assert json.loads((root / "schemas/analysis-context-v1.schema.json").read_text()) == AnalysisContext.model_json_schema()
    assert (
        json.loads((root / "schemas/analysis-context-event-v1.schema.json").read_text())
        == AnalysisContextEvent.model_json_schema()
    )


def test_architecture_doc_names_every_normative_event_and_schema() -> None:
    root = Path(__file__).resolve().parents[4]
    text = (root / "docs/architecture/analysis-context.md").read_text(encoding="utf-8")
    assert "schemas/analysis-context-v1.schema.json" in text
    assert "schemas/analysis-context-event-v1.schema.json" in text
    for event_type in get_args(EventType):
        assert f"`{event_type}`" in text
