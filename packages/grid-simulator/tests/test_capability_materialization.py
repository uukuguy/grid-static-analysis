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
VERIFICATION = ROOT / "configs/capabilities/pandapower-3.4.0-verification.json"


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


def test_every_matrix_row_has_single_composition_failure_and_held_out_evidence() -> None:
    matrix_rows = {
        row["id"]
        for row in json.loads(MATRIX.read_text(encoding="utf-8"))["rows"]
        if row["scope"] == "in_scope"
    }
    verification = json.loads(VERIFICATION.read_text(encoding="utf-8"))
    lanes = set(verification["required_lanes"])
    rows = verification["rows"]

    assert lanes == {"single", "composition", "failure", "held_out"}
    assert {row["id"] for row in rows} == matrix_rows
    assert len(rows) == len(matrix_rows) == 24
    for row in rows:
        assert set(row) == {"id", *lanes}
        for lane in lanes:
            evidence_path = ROOT / row[lane]
            assert evidence_path.is_file(), f"{row['id']} {lane}: {row[lane]}"
