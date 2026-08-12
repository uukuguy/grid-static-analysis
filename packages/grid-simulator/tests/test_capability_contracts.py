from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from grid_simulator.capabilities import CapabilityRegistry
from grid_simulator.capabilities.schema import CapabilityContract


EXPECTED_IDS = (
    "analysis.contingency.n_minus_one.run",
    "analysis.powerflow.ac.run",
    "context.get",
    "context.open",
    "environment.describe",
    "evidence.get",
    "model.dataset.describe",
    "model.dataset.query",
    "model.element.get",
    "model.list",
    "result.branches.rank",
    "topology.branch.endpoints.get",
    "topology.components.get",
)


def test_packaged_contracts_cover_all_wp_a_capabilities() -> None:
    registry = CapabilityRegistry.load_packaged()

    assert tuple(contract.id for contract in registry.list()) == EXPECTED_IDS
    assert all(isinstance(contract, CapabilityContract) for contract in registry.list())


def test_contracts_have_unique_ids_and_tool_names() -> None:
    contracts = CapabilityRegistry.load_packaged().list()

    assert len({contract.id for contract in contracts}) == len(contracts)
    assert len({contract.tool_name for contract in contracts}) == len(contracts)


@pytest.mark.parametrize("identifier", EXPECTED_IDS)
def test_contracts_include_semantic_terms_and_composition(identifier: str) -> None:
    contract = CapabilityRegistry.load_packaged().require(identifier)

    assert contract.terms["zh"]
    assert contract.terms["en"]
    assert contract.applies_to
    assert contract.not_for
    assert contract.consumes or contract.produces
    assert contract.errors
    assert contract.recovery
    assert contract.input_schema["type"] == "object"
    assert contract.output_schema["type"] == "object"
    assert contract.input_schema["additionalProperties"] is False
    assert contract.output_schema["additionalProperties"] is False


def test_unknown_contract_is_actionable() -> None:
    registry = CapabilityRegistry.load_packaged()

    with pytest.raises(KeyError, match="unknown capability"):
        registry.require("missing.capability")


def test_reference_fields_have_exact_prefix_patterns() -> None:
    registry = CapabilityRegistry.load_packaged()
    expected_patterns = {
        "context_ref": r"^context:sha256:[0-9a-f]{64}$",
        "branch_ref": r"^asset:(line|trafo|trafo3w):sha256:[0-9a-f]{64}$",
        "element_ref": r"^asset:[a-z0-9_]+:sha256:[0-9a-f]{64}$",
        "dataset_ref": r"^dataset:network\.(buses|branches):sha256:[0-9a-f]{64}$",
        "result_ref": r"^result:sha256:[0-9a-f]{64}$",
        "evidence_ref": r"^evidence:sha256:[0-9a-f]{64}$",
    }

    for contract in registry.list():
        for field, schema in _walk_properties(contract.input_schema):
            if field in expected_patterns:
                assert schema["pattern"] == expected_patterns[field], f"{contract.id}:{field}"


def test_dataset_query_uses_dataset_specific_selectable_field_enums() -> None:
    contract = CapabilityRegistry.load_packaged().require("model.dataset.query")
    branches = contract.input_schema["oneOf"]

    assert len(branches) == 2
    dataset_enums = {branch["properties"]["dataset"]["const"] for branch in branches}
    assert dataset_enums == {"network.buses", "network.branches"}
    assert "fields" not in contract.input_schema["properties"]
    for branch in branches:
        fields = branch["properties"]["select"]["items"]
        assert "enum" in fields
        assert fields["enum"]
        assert fields.get("type") != "string"


def test_dataset_query_schema_validates_bus_payload_and_rejects_unknown_properties() -> None:
    contract = CapabilityRegistry.load_packaged().require("model.dataset.query")
    validator = Draft202012Validator(contract.input_schema)
    valid_bus_query = {
        "context_ref": "context:sha256:" + "a" * 64,
        "dataset": "network.buses",
        "select": ["index", "name", "vn_kv"],
        "where": {"name": "16"},
        "limit": 10,
    }

    validator.validate(valid_bus_query)
    with pytest.raises(JsonSchemaValidationError):
        validator.validate({**valid_bus_query, "unexpected": True})


def test_analysis_contracts_bind_to_pandapower_340() -> None:
    registry = CapabilityRegistry.load_packaged()
    for identifier in ("analysis.powerflow.ac.run", "analysis.contingency.n_minus_one.run"):
        contract = registry.require(identifier)
        assert contract.pandapower is not None
        assert contract.pandapower.version == "3.4.0"
        assert contract.pandapower.operation


def test_all_nested_object_schemas_forbid_extra_properties() -> None:
    for contract in CapabilityRegistry.load_packaged().list():
        for schema in _walk_object_schemas(contract.input_schema):
            assert schema.get("additionalProperties") is False, contract.id
        for schema in _walk_object_schemas(contract.output_schema):
            assert schema.get("additionalProperties") is False, contract.id


def _walk_properties(schema: object) -> list[tuple[str, dict[str, object]]]:
    found: list[tuple[str, dict[str, object]]] = []
    if not isinstance(schema, dict):
        return found
    properties = schema.get("properties", {})
    if isinstance(properties, dict):
        for key, value in properties.items():
            if isinstance(value, dict):
                found.append((str(key), value))
                found.extend(_walk_properties(value))
    for branch_key in ("oneOf", "anyOf", "allOf"):
        branches = schema.get(branch_key, [])
        if isinstance(branches, list):
            for branch in branches:
                found.extend(_walk_properties(branch))
    items = schema.get("items")
    if isinstance(items, dict):
        found.extend(_walk_properties(items))
    return found


def _walk_object_schemas(schema: object) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    if not isinstance(schema, dict):
        return found
    if schema.get("type") == "object":
        found.append(schema)
    for key in ("properties", "items"):
        value = schema.get(key)
        if isinstance(value, dict):
            values = value.values() if key == "properties" else (value,)
            for item in values:
                found.extend(_walk_object_schemas(item))
    for branch_key in ("oneOf", "anyOf", "allOf"):
        branches = schema.get(branch_key, [])
        if isinstance(branches, list):
            for branch in branches:
                found.extend(_walk_object_schemas(branch))
    return found
