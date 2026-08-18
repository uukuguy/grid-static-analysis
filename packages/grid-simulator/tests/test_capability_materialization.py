from __future__ import annotations

import json
from pathlib import Path

from grid_simulator.analysis_registry import AnalysisRegistry
from grid_simulator.capabilities import CapabilityRegistry
from grid_simulator.creators import CreatorRegistry
from grid_simulator.operations import EXECUTABLE_CAPABILITIES


ROOT = Path(__file__).resolve().parents[3]
MATRIX = ROOT / "configs/capabilities/pandapower-3.4.0-static-analysis.json"
MATERIALIZATION = ROOT / "configs/capabilities/pandapower-3.4.0-materialization.json"


def test_every_published_matrix_row_has_executable_materialization() -> None:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    materialization = json.loads(MATERIALIZATION.read_text(encoding="utf-8"))
    published = {row["id"] for row in matrix["rows"] if row["scope"] == "in_scope"}
    mapped = {row["id"] for row in materialization["rows"]}

    assert published == mapped
    assert len(mapped) == len(materialization["rows"]) == 24


def test_materialization_references_only_live_contracts_operations_and_creators() -> None:
    rows = json.loads(MATERIALIZATION.read_text(encoding="utf-8"))["rows"]
    contracts = {contract.id for contract in CapabilityRegistry.load_packaged().list()}
    operations = {operation.identifier for operation in AnalysisRegistry().list()}
    creators = set(CreatorRegistry().list())

    referenced_capabilities = {item for row in rows for item in row["capabilities"]}
    referenced_operations = {item for row in rows for item in row["operations"]}
    referenced_creators = {item for row in rows for item in row["creators"]}

    assert referenced_capabilities <= contracts == EXECUTABLE_CAPABILITIES
    assert referenced_operations == operations
    assert referenced_creators <= creators


def test_all_analysis_options_and_result_tables_are_discoverable_without_generic_tools() -> None:
    contracts = CapabilityRegistry.load_packaged()
    assert {"analysis.operation.list", "analysis.operation.describe", "result.dataset.list", "result.dataset.describe"} <= {
        contract.id for contract in contracts.list()
    }
    for operation in AnalysisRegistry().list():
        description = AnalysisRegistry().describe(operation.identifier)
        assert description["options_schema"]["additionalProperties"] is False

    prohibited = {"shell", "bash", "python", "file.read", "file.write", "pandapower.raw"}
    capability_ids = {contract.id for contract in contracts.list()}
    tool_names = {contract.tool_name for contract in contracts.list()}
    assert not prohibited & capability_ids
    assert not {"read", "write", "edit", "shell", "bash", "python"} & tool_names
