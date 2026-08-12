from grid_agent.validation.oracles import ToolResultEvent, contains_all, topology_branch_endpoints, truthful_limitation


def test_contains_all_matches_required_values_case_insensitively() -> None:
    assert contains_all("正常范围为 0.95 到 1.05 PU。", {"values": ["0.95", "1.05", "pu"]})
    assert not contains_all("正常范围为 0.95 到 1.04 pu。", {"values": ["0.95", "1.05", "pu"]})


def test_truthful_limitation_matches_known_limitation_terms() -> None:
    assert truthful_limitation("line:index:171 not found in ieee39", {})
    assert not truthful_limitation("线路 line:index:171 的最大负载率为 30%。", {})


def test_topology_oracle_matches_declared_result_fields() -> None:
    event = ToolResultEvent(
        capability="topology.branch.endpoints.get",
        result={
            "branch": {"kind": "line", "namespace": "pandapower_index", "identifier": "11"},
            "from_bus": {"name": "6", "asset_ref": "asset:bus:sha256:" + "a" * 64},
            "to_bus": {"name": "11", "asset_ref": "asset:bus:sha256:" + "b" * 64},
        },
        evidence_refs=("evidence:sha256:" + "c" * 64,),
    )
    expected = {
        "branch": {"kind": "line", "namespace": "pandapower_index", "identifier": "11"},
        "from_bus": {"name": "6"},
        "to_bus": {"name": "11"},
    }
    assert topology_branch_endpoints(event, expected) is True


def test_topology_oracle_rejects_wrong_structured_endpoint_even_when_prose_is_polished() -> None:
    event = ToolResultEvent(
        capability="topology.branch.endpoints.get",
        result={"from_bus": {"name": "6"}, "to_bus": {"name": "12"}},
        evidence_refs=("evidence:sha256:" + "d" * 64,),
    )
    assert topology_branch_endpoints(event, {"from_bus": {"name": "6"}, "to_bus": {"name": "11"}}) is False
