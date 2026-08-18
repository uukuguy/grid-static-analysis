from __future__ import annotations

from pathlib import Path

from grid_simulator.operations import dispatch
from grid_simulator.protocol import GridCapabilityRequest


def _request(capability: str, arguments: dict[str, object]) -> GridCapabilityRequest:
    return GridCapabilityRequest(
        protocol="grid-capability",
        protocol_version="1.0",
        request_id=f"req-{capability}",
        capability=capability,
        arguments=arguments,
    )


def test_declarative_model_creation_resolves_local_element_references(tmp_path: Path) -> None:
    response = dispatch(
        _request(
            "model.create",
            {
                "name": "one-bus-short-circuit",
                "sn_mva": 100.0,
                "f_hz": 50.0,
                "elements": [
                    {"id": "source_bus", "creator": "bus", "arguments": {"vn_kv": 110.0}},
                    {
                        "id": "source",
                        "creator": "ext_grid",
                        "arguments": {
                            "bus": {"element_ref": "source_bus"},
                            "vm_pu": 1.0,
                            "s_sc_max_mva": 5000.0,
                            "rx_max": 0.1,
                        },
                    },
                ],
            },
        ),
        tmp_path,
    )

    assert response.ok is True
    assert response.result is not None
    assert response.result["model"] == "created:one-bus-short-circuit"
    assert response.result["origin"] == "created"
    assert response.result["counts"] == {"buses": 1, "lines": 0, "transformers": 0}
    context_ref = response.result["context_ref"]
    ext_grid = dispatch(
        _request(
            "model.dataset.query",
            {
                "context_ref": context_ref,
                "dataset": "network.ext_grid",
                "select": ["index", "bus", "s_sc_max_mva", "rx_max"],
            },
        ),
        tmp_path,
    )
    assert ext_grid.ok is True
    assert ext_grid.result is not None
    assert ext_grid.result["rows"] == [{"index": 0, "bus": 0, "s_sc_max_mva": 5000.0, "rx_max": 0.1}]


def test_model_create_rejects_non_allowlisted_creator_without_artifacts(tmp_path: Path) -> None:
    response = dispatch(
        _request(
            "model.create",
            {
                "name": "unsafe",
                "elements": [{"id": "x", "creator": "python", "arguments": {"code": "raise SystemExit"}}],
            },
        ),
        tmp_path,
    )

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "unknown_creator"
    assert not (tmp_path / "evidence").exists()


def test_creator_registry_is_discoverable_and_describes_pinned_signatures(tmp_path: Path) -> None:
    listed = dispatch(_request("model.creator.list", {}), tmp_path)

    assert listed.ok is True
    assert listed.result is not None
    assert listed.result["pandapower_version"] == "3.4.0"
    creators = {item["id"]: item for item in listed.result["creators"]}
    assert creators["bus"]["required_arguments"] == ["vn_kv"]
    assert "ext_grid" in creators

    described = dispatch(_request("model.creator.describe", {"creator": "ext_grid"}), tmp_path)
    assert described.ok is True
    assert described.result is not None
    assert described.result["creator"] == "ext_grid"
    parameters = {item["name"]: item for item in described.result["parameters"]}
    assert parameters["bus"]["required"] is True
    assert parameters["bus"]["accepts_element_ref"] is True
    assert parameters["vm_pu"]["required"] is False
    assert described.result["local_reference"] == {
        "syntax": {"element_ref": "<earlier_local_id>"},
        "ordering": "The referenced element must appear earlier in the same transaction.",
    }


def test_creator_describe_rejects_unknown_creator_with_actionable_catalog(tmp_path: Path) -> None:
    response = dispatch(_request("model.creator.describe", {"creator": "python"}), tmp_path)

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "unknown_creator"
    assert "bus" in response.error.details["allowed_creators"]


def test_revision_derivation_scales_loads_transactionally_and_preserves_parent(tmp_path: Path) -> None:
    opened = dispatch(_request("context.open", {"model_id": "ieee39"}), tmp_path)
    assert opened.ok is True and opened.result is not None
    parent_context = str(opened.result["context_ref"])
    parent_revision = str(opened.result["semantic_sha256"])
    parent_artifact = tmp_path / "evidence" / "models" / f"{parent_revision}.json"
    parent_bytes = parent_artifact.read_bytes()

    derived = dispatch(
        _request(
            "model.revision.derive",
            {
                "context_ref": parent_context,
                "patches": [
                    {
                        "operation": "scale",
                        "kind": "load",
                        "selector": {"where": {"in_service": True}},
                        "fields": ["p_mw", "q_mvar"],
                        "factor": 1.05,
                    }
                ],
            },
        ),
        tmp_path,
    )

    assert derived.ok is True
    assert derived.result is not None
    assert derived.result["origin"] == "derived"
    assert derived.result["parent_context_ref"] == parent_context
    assert derived.result["context_ref"] != parent_context
    parent = dispatch(_request("context.get", {"context_ref": parent_context}), tmp_path)
    assert parent.ok is True
    assert opened.result["semantic_sha256"] == parent_revision
    assert parent_artifact.read_bytes() == parent_bytes
    assert derived.result["lineage_ref"].startswith("lineage:sha256:")


def test_distinct_derivations_with_same_network_content_keep_distinct_lineage(tmp_path: Path) -> None:
    opened = dispatch(_request("context.open", {"model_id": "ieee39"}), tmp_path)
    assert opened.ok is True and opened.result is not None

    first = dispatch(
        _request(
            "model.revision.derive",
            {
                "context_ref": opened.result["context_ref"],
                "patches": [
                    {"operation": "scale", "kind": "load", "selector": {"indices": [0]}, "fields": ["p_mw"], "factor": 1.0}
                ]
            },
        ),
        tmp_path,
    )
    second = dispatch(
        _request(
            "model.revision.derive",
            {
                "context_ref": opened.result["context_ref"],
                "patches": [
                    {"operation": "set", "kind": "load", "selector": {"indices": [0]}, "values": {"p_mw": 97.60000000000001}}
                ]
            },
        ),
        tmp_path,
    )

    assert first.ok is True and first.result is not None
    assert second.ok is True and second.result is not None
    assert first.result["revision_ref"] == second.result["revision_ref"]
    assert first.result["lineage_ref"] != second.result["lineage_ref"]
    assert first.result["context_ref"] != second.result["context_ref"]


def test_revision_derivation_rolls_back_all_patches_after_invalid_field(tmp_path: Path) -> None:
    opened = dispatch(_request("context.open", {"model_id": "ieee39"}), tmp_path)
    assert opened.ok is True and opened.result is not None
    before = set((tmp_path / "evidence" / "models").glob("*.json"))

    derived = dispatch(
        _request(
            "model.revision.derive",
            {
                "context_ref": opened.result["context_ref"],
                "patches": [
                    {"operation": "in_service", "kind": "line", "selector": {"indices": [0]}, "value": False},
                    {"operation": "set", "kind": "load", "selector": {"indices": [0]}, "values": {"python": 1}},
                ],
            },
        ),
        tmp_path,
    )

    assert derived.ok is False
    assert derived.error is not None
    assert derived.error.code == "patch_field_unavailable"
    assert set((tmp_path / "evidence" / "models").glob("*.json")) == before


def test_revision_derivation_supports_create_and_referential_drop_patches(tmp_path: Path) -> None:
    created = dispatch(
        _request(
            "model.create",
            {
                "name": "revision-operations",
                "elements": [
                    {"id": "bus_a", "creator": "bus", "arguments": {"vn_kv": 20.0}},
                    {"id": "bus_b", "creator": "bus", "arguments": {"vn_kv": 20.0}},
                    {
                        "id": "line",
                        "creator": "line_from_parameters",
                        "arguments": {
                            "from_bus": {"element_ref": "bus_a"},
                            "to_bus": {"element_ref": "bus_b"},
                            "length_km": 1.0,
                            "r_ohm_per_km": 0.1,
                            "x_ohm_per_km": 0.1,
                            "c_nf_per_km": 0.0,
                            "max_i_ka": 1.0
                        }
                    }
                ]
            },
        ),
        tmp_path,
    )
    assert created.ok is True and created.result is not None

    derived = dispatch(
        _request(
            "model.revision.derive",
            {
                "context_ref": created.result["context_ref"],
                "patches": [
                    {
                        "operation": "create",
                        "id": "load_a",
                        "creator": "load",
                        "arguments": {"bus": 0, "p_mw": 1.0, "q_mvar": 0.2}
                    },
                    {"operation": "drop", "kind": "line", "selector": {"indices": [0]}}
                ]
            },
        ),
        tmp_path,
    )

    assert derived.ok is True and derived.result is not None
    context_ref = derived.result["context_ref"]
    datasets = dispatch(_request("model.dataset.list", {"context_ref": context_ref}), tmp_path)
    assert datasets.ok is True and datasets.result is not None
    counts = {item["dataset"]: item["row_count"] for item in datasets.result["datasets"]}
    assert counts["network.load"] == 1
    assert counts["network.line"] == 0


def test_revision_derivation_applies_branch_outage_and_switch_state(tmp_path: Path) -> None:
    created = dispatch(
        _request(
            "model.create",
            {
                "name": "switch-state",
                "elements": [
                    {"id": "bus_a", "creator": "bus", "arguments": {"vn_kv": 20.0}},
                    {"id": "bus_b", "creator": "bus", "arguments": {"vn_kv": 20.0}},
                    {
                        "id": "line",
                        "creator": "line_from_parameters",
                        "arguments": {
                            "from_bus": {"element_ref": "bus_a"}, "to_bus": {"element_ref": "bus_b"},
                            "length_km": 1.0, "r_ohm_per_km": 0.1, "x_ohm_per_km": 0.1,
                            "c_nf_per_km": 0.0, "max_i_ka": 1.0
                        }
                    },
                    {
                        "id": "switch", "creator": "switch",
                        "arguments": {"bus": {"element_ref": "bus_a"}, "element": {"element_ref": "line"}, "et": "l", "closed": True}
                    }
                ]
            },
        ),
        tmp_path,
    )
    assert created.ok is True and created.result is not None

    derived = dispatch(
        _request(
            "model.revision.derive",
            {
                "context_ref": created.result["context_ref"],
                "patches": [
                    {"operation": "in_service", "kind": "line", "selector": {"indices": [0]}, "value": False},
                    {"operation": "switch_state", "kind": "switch", "selector": {"indices": [0]}, "closed": False}
                ]
            },
        ),
        tmp_path,
    )
    assert derived.ok is True and derived.result is not None

    line = dispatch(
        _request("model.dataset.query", {"context_ref": derived.result["context_ref"], "dataset": "network.line", "select": ["index", "in_service"]}),
        tmp_path,
    )
    switch = dispatch(
        _request("model.dataset.query", {"context_ref": derived.result["context_ref"], "dataset": "network.switch", "select": ["index", "closed"]}),
        tmp_path,
    )
    assert line.ok is True and line.result is not None and line.result["rows"] == [{"index": 0, "in_service": False}]
    assert switch.ok is True and switch.result is not None and switch.result["rows"] == [{"index": 0, "closed": False}]


def test_revision_contract_rejects_operation_missing_required_payload_before_loading_context(tmp_path: Path) -> None:
    response = dispatch(
        _request(
            "model.revision.derive",
            {
                "context_ref": "context:sha256:" + "a" * 64,
                "patches": [
                    {"operation": "scale", "kind": "load", "selector": {"indices": [0]}, "fields": ["p_mw"]}
                ]
            },
        ),
        tmp_path,
    )

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "invalid_arguments"
    assert response.error.phase == "validate"
