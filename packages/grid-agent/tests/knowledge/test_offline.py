from __future__ import annotations

import importlib
import sys


def test_information_answers_cover_only_reviewed_concepts() -> None:
    offline = importlib.import_module("grid_agent.knowledge.offline")

    n_minus_one = offline.answer_information("N-1静态安全校核需要检查哪些越限类型?")
    ac_inputs = offline.answer_information("某个潮流计算工具需要输入哪些参数?")

    assert offline.answer_information("母线电压正常运行范围是多少?") is None
    assert n_minus_one is not None and "电压" in n_minus_one and "过载" in n_minus_one
    assert ac_inputs is not None and "context_ref" in ac_inputs and "analysis.powerflow.ac.run" in ac_inputs
    assert offline.answer_information("IEEE-39节点系统中线路11连接哪两个母线?") is None


def test_offline_n_minus_one_has_no_legacy_policy_argument() -> None:
    offline = importlib.import_module("grid_agent.knowledge.offline")

    class RecordingClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def invoke(self, capability: str, arguments: dict[str, object]) -> dict[str, object]:
            self.calls.append((capability, arguments))
            if capability == "context.open":
                return {"context_ref": "context:test"}
            if capability == "model.element.get":
                return {"element": {"asset_ref": "asset:line:test"}}
            return {
                "result_ref": "result:test",
                "scenarios": [
                    {
                        "status": "succeeded",
                        "violations": [],
                        "max_loading_percent": 80.0,
                        "evidence_ref": "evidence:test",
                    }
                ],
            }

    client = RecordingClient()
    offline.answer_diagnostic("对 IEEE-39 节点系统线路11开展 N-1 校核", client)

    n1_call = next(item for item in client.calls if item[0] == "analysis.contingency.n_minus_one.run")
    assert "policy" not in n1_call[1]


def test_offline_knowledge_import_does_not_load_simulator_modules() -> None:
    for name in list(sys.modules):
        if name.startswith("grid_simulator") or name == "pandapower" or name.startswith("pandapower."):
            del sys.modules[name]

    importlib.import_module("grid_agent.knowledge.offline")

    assert "grid_simulator" not in sys.modules
    assert "pandapower" not in sys.modules
