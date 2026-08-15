from __future__ import annotations

import json
from pathlib import Path

import pytest

from grid_agent.tools.catalog import ToolCatalog, ToolCatalogError


def test_catalog_preserves_semantic_tool_description(
    capability_documents: tuple[dict[str, object], ...],
) -> None:
    catalog = ToolCatalog.from_documents(capability_documents)

    tool = catalog.require("grid_topology_branch_endpoints")

    assert "连接" in tool.description
    assert "不表示实时功率方向" in tool.description
    assert tool.input_schema["additionalProperties"] is False


def test_catalog_filters_to_environment_executable_capabilities(
    capability_documents: tuple[dict[str, object], ...],
) -> None:
    catalog = ToolCatalog.from_environment(
        capability_documents,
        {
            "executable_capabilities": [
                {"id": "environment.describe"},
                {"id": "topology.branch.endpoints.get"},
            ]
        },
    )

    assert [tool.capability for tool in catalog.tools] == [
        "environment.describe",
        "grid_record_decision",
        "topology.branch.endpoints.get",
    ]


def test_catalog_materializes_deterministic_sorted_json(
    capability_documents: tuple[dict[str, object], ...], tmp_path: Path
) -> None:
    catalog = ToolCatalog.from_environment(
        capability_documents,
        {
            "executable_capabilities": [
                {"id": "topology.branch.endpoints.get"},
                {"id": "environment.describe"},
            ]
        },
    )

    first = catalog.materialize(tmp_path / "catalog-a.json")
    second = catalog.materialize(tmp_path / "catalog-b.json")

    first_payload = json.loads(first.read_text(encoding="utf-8"))
    second_payload = json.loads(second.read_text(encoding="utf-8"))
    assert first_payload == second_payload
    assert first_payload["fingerprint"].startswith("sha256:")
    assert [tool["name"] for tool in first_payload["tools"]] == [
        "grid_environment_describe",
        "grid_record_decision",
        "grid_topology_branch_endpoints",
    ]


def test_catalog_publishes_bounded_decision_as_agent_intent(
    capability_documents: tuple[dict[str, object], ...],
) -> None:
    catalog = ToolCatalog.from_documents(capability_documents)

    decision = catalog.require("grid_record_decision")

    assert decision.capability == "grid_record_decision"
    assert "agent intent" in decision.description
    assert "not simulator truth" in decision.description
    assert decision.input_schema["properties"]["intent"] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 500,
    }
    assert decision.input_schema["properties"]["refs"]["maxItems"] == 20


def test_catalog_rejects_schema_drift() -> None:
    with pytest.raises(ToolCatalogError, match="input_schema"):
        ToolCatalog.from_documents(
            [
                {
                    "id": "bad.capability",
                    "tool_name": "grid_bad",
                    "availability": "published",
                    "context_effect": {
                        "requires_state": [],
                        "consumes_state": ["test.input"],
                        "produces_state": ["test.output"],
                        "invalidates_state": [],
                        "result_kind": None,
                        "projector": "test-v1",
                    },
                    "purpose": "test",
                    "applies_to": [],
                    "not_for": [],
                    "input_schema": {"type": "not-a-json-schema-type"},
                    "requires": [],
                    "produces": [],
                    "common_next": [],
                    "recovery": {},
                }
            ]
        )


def test_catalog_rejects_non_published_executable_document(
    capability_documents: tuple[dict[str, object], ...],
) -> None:
    environment = next(item for item in capability_documents if item["id"] == "environment.describe")
    unpublished = {**environment, "availability": "not_published"}

    with pytest.raises(ToolCatalogError, match="not published"):
        ToolCatalog.from_environment(
            [unpublished],
            {"executable_capabilities": [{"id": "environment.describe"}]},
        )
