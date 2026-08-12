from grid_agent.validation.oracles import branch_endpoints, contains_all, truthful_limitation


def test_contains_all_matches_required_values_case_insensitively() -> None:
    assert contains_all("正常范围为 0.95 到 1.05 PU。", {"values": ["0.95", "1.05", "pu"]})
    assert not contains_all("正常范围为 0.95 到 1.04 pu。", {"values": ["0.95", "1.05", "pu"]})


def test_truthful_limitation_matches_known_limitation_terms() -> None:
    assert truthful_limitation("line:index:171 not found in ieee39", {})
    assert not truthful_limitation("线路 line:index:171 的最大负载率为 30%。", {})


def test_branch_endpoints_matches_bus_number_tokens_only() -> None:
    assert branch_endpoints("线路11连接母线6与母线11。", {"bus_names": ["6", "11"]})
    assert not branch_endpoints("线路11连接母线16与母线21。", {"bus_names": ["6", "11"]})


def test_branch_endpoints_uses_only_bus_context_numbers() -> None:
    assert not branch_endpoints("线路11连接母线6与母线12。", {"bus_names": ["6", "11"]})
    assert branch_endpoints("线路11连接母线6与母线11。", {"bus_names": ["6", "11"]})
    assert branch_endpoints("Line 11 connects bus 6 and bus 11.", {"bus_names": ["6", "11"]})


def test_branch_endpoints_accepts_bounded_endpoint_phrases() -> None:
    assert branch_endpoints("线路 line:index:11 连接母线 6 与 11。", {"bus_names": ["6", "11"]})
    assert branch_endpoints("Line 11 connects buses 6 and 11.", {"bus_names": ["6", "11"]})
    assert not branch_endpoints("线路 line:index:11 连接母线 6，额定电压为 11 kV。", {"bus_names": ["6", "11"]})


def test_branch_endpoints_rejects_english_comma_unit_descriptor() -> None:
    assert not branch_endpoints("Line 11 connects bus 6, 11 kV base.", {"bus_names": ["6", "11"]})


def test_branch_endpoints_rejects_chinese_comma_unit_descriptor() -> None:
    assert not branch_endpoints("线路11连接母线6，11 kV基准电压。", {"bus_names": ["6", "11"]})


def test_branch_endpoints_rejects_unit_descriptors_after_endpoint_separators() -> None:
    assert not branch_endpoints("Line 11 connects bus 6 and 11 kV base.", {"bus_names": ["6", "11"]})
    assert not branch_endpoints("线路11连接母线6与11基准电压。", {"bus_names": ["6", "11"]})


def test_branch_endpoints_accepts_repeated_bus_markers_after_commas() -> None:
    assert branch_endpoints("Line 11 connects bus 6, bus 11.", {"bus_names": ["6", "11"]})
    assert branch_endpoints("线路11连接母线6，母线11。", {"bus_names": ["6", "11"]})
