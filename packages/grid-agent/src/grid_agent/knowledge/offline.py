from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol


class CapabilityClient(Protocol):
    def invoke(self, capability: str, arguments: dict[str, object]) -> dict[str, object]:
        ...


@dataclass(frozen=True)
class KnowledgeEntry:
    concept_id: str
    source_id: str
    answer: str


@dataclass(frozen=True)
class DiagnosticPlan:
    intent: Literal["line_endpoints", "powerflow", "ranking", "n_minus_one", "fault_ranking"]
    model_id: str
    line_id: str | None = None


_ENTRIES = (
    KnowledgeEntry(
        concept_id="static-analysis-v1.voltage-normal-range",
        source_id="knowledge/policies/static-analysis-v1.md",
        answer="静态分析策略 static-analysis-v1 中，母线电压正常运行范围为 0.95–1.05 p.u.。",
    ),
    KnowledgeEntry(
        concept_id="static-analysis-v1.n-minus-one-violation-types",
        source_id="knowledge/analyses/n-minus-one.md",
        answer=(
            "N-1 静态安全校核检查潮流不收敛、母线低电压、母线高电压，"
            "以及线路/变压器等支路过载。"
        ),
    ),
    KnowledgeEntry(
        concept_id="analysis.powerflow.ac.run.inputs",
        source_id="skills/grid-static-analysis/references/ac-powerflow.md",
        answer=(
            "交流潮流能力 analysis.powerflow.ac.run 的必需输入是已打开模型的 context_ref；"
            "可选输入包括 solver_profile、algorithm、init、max_iteration、tolerance_mva、"
            "trafo_model、trafo_loading、enforce_q_lims 与 check_connectivity。"
        ),
    ),
)

_SUPPORTED_OFFLINE_MODEL_ID = "ieee39"
_SUPPORTED_OFFLINE_LINE_IDS = frozenset({"11"})


def answer_information(question: str) -> str | None:
    normalized = question.lower()
    if "电压" in question and ("范围" in question or "正常" in question):
        return _with_source(_ENTRIES[0])
    if "n-1" in normalized and ("哪些" in question or "什么" in question or "类型" in question):
        return _with_source(_ENTRIES[1])
    if "输入" in question and "潮流" in question:
        return _with_source(_ENTRIES[2])
    return None


def answer_diagnostic(question: str, client: CapabilityClient) -> str:
    plan = plan_diagnostic(question)
    if isinstance(plan, str):
        return plan

    opened = client.invoke("context.open", {"model_id": plan.model_id})
    context_ref = str(opened["context_ref"])

    if plan.intent == "line_endpoints":
        line_id = str(plan.line_id)
        return _answer_line_endpoints(client, context_ref, line_id)

    if plan.intent == "ranking":
        powerflow = client.invoke("analysis.powerflow.ac.run", {"context_ref": context_ref})
        ranking = client.invoke(
            "result.branches.rank",
            {
                "result_ref": str(powerflow["result_ref"]),
                "metric": "loading_percent",
                "direction": "descending",
                "limit": 5,
                "element_kind": "line",
            },
        )
        return _answer_ranking(ranking, powerflow)

    if plan.intent == "n_minus_one":
        line_id = str(plan.line_id)
        element = client.invoke(
            "model.element.get",
            {
                "context_ref": context_ref,
                "kind": "line",
                "namespace": "pandapower_index",
                "identifier": line_id,
            },
        )
        branch_ref = str(dict(element["element"])["asset_ref"])
        result = client.invoke(
            "analysis.contingency.n_minus_one.run",
            {"context_ref": context_ref, "branch_refs": [branch_ref], "policy": "static-analysis-v1"},
        )
        return _answer_n_minus_one(result, line_id)

    if plan.intent == "fault_ranking":
        powerflow = client.invoke("analysis.powerflow.ac.run", {"context_ref": context_ref})
        ranking = client.invoke(
            "result.branches.rank",
            {
                "result_ref": str(powerflow["result_ref"]),
                "metric": "loading_percent",
                "direction": "descending",
                "limit": 5,
                "element_kind": "line",
            },
        )
        branch_refs = [str(branch["branch_ref"]) for branch in ranking["branches"]]
        result = client.invoke(
            "analysis.contingency.n_minus_one.run",
            {"context_ref": context_ref, "branch_refs": branch_refs, "policy": "static-analysis-v1"},
        )
        return _answer_fault_ranking(result)

    if plan.intent == "powerflow":
        powerflow = client.invoke("analysis.powerflow.ac.run", {"context_ref": context_ref})
        return _answer_powerflow(powerflow)

    raise AssertionError(f"unhandled offline diagnostic intent: {plan.intent}")


def plan_diagnostic(question: str) -> DiagnosticPlan | str:
    intent = _diagnostic_intent(question)
    if intent is None:
        return (
            "执行限制 / execution limitation: 离线诊断路径只支持已审核的信息概念、明确 IEEE-39 模型的"
            "线路11端点、交流潮流、有功网损、线路负载率排序和 N-1 静态安全校核。"
        )

    model_id = _model_id(question)
    if model_id is None:
        model_name = _explicit_ieee_model_name(question)
        if model_name is not None:
            return (
                f"执行限制 / execution limitation: 当前离线诊断路径不支持 {model_name}；"
                "仅支持明确请求已注册的 IEEE-39 模型，且不会创建仿真运行。"
            )
        return (
            f"执行限制 / execution limitation: {_intent_label(intent)}需要在问题中明确指定已注册的 IEEE-39 模型，"
            "当前请求缺少可识别模型，未创建仿真运行。"
        )

    if intent == "line_endpoints":
        line_id = _line_identifier(question)
        if line_id not in _SUPPORTED_OFFLINE_LINE_IDS:
            return _unsupported_line_limitation(line_id)
        return DiagnosticPlan(intent=intent, model_id=model_id, line_id=line_id)

    if intent == "n_minus_one":
        line_id = _line_identifier(question)
        if line_id not in _SUPPORTED_OFFLINE_LINE_IDS:
            return _unsupported_line_limitation(line_id, prefix="N-1 静态安全校核")
        return DiagnosticPlan(intent=intent, model_id=model_id, line_id=line_id)

    return DiagnosticPlan(intent=intent, model_id=model_id)


def _diagnostic_intent(
    question: str,
) -> Literal["line_endpoints", "powerflow", "ranking", "n_minus_one", "fault_ranking"] | None:
    if _asks_line_endpoints(question):
        return "line_endpoints"
    if "故障" in question and "排序" in question:
        return "fault_ranking"
    if "负载率最高" in question:
        return "ranking"
    if _asks_n_minus_one(question):
        return "n_minus_one"
    if "潮流" in question and any(term in question for term in ("运行", "输出", "网损", "有功")):
        return "powerflow"
    return None


def _model_id(question: str) -> str | None:
    return _SUPPORTED_OFFLINE_MODEL_ID if re.search(r"ieee\s*-?\s*39(?!\d)", question, flags=re.IGNORECASE) else None


def _explicit_ieee_model_name(question: str) -> str | None:
    match = re.search(r"ieee\s*-?\s*(\d+)(?!\d)", question, flags=re.IGNORECASE)
    if match is None:
        return None
    return f"IEEE-{match.group(1)}"


def _intent_label(intent: str) -> str:
    labels = {
        "line_endpoints": "线路端点查询",
        "powerflow": "交流潮流诊断",
        "ranking": "线路负载率排序",
        "n_minus_one": "N-1 静态安全校核",
        "fault_ranking": "故障分析排序",
    }
    return labels.get(intent, "离线仿真诊断")


def _unsupported_line_limitation(line_id: str | None, *, prefix: str = "离线诊断") -> str:
    if line_id is None:
        return (
            f"执行限制 / execution limitation: {prefix} 需要明确且受支持的线路目标；"
            "当前请求缺少可识别线路编号，未创建仿真运行。"
        )
    return (
        f"执行限制 / execution limitation: {prefix} 当前离线烟测只支持 IEEE-39 的线路11；"
        f"线路{line_id}不是此离线路径中可识别的受支持目标，未创建仿真运行。"
    )


def _with_source(entry: KnowledgeEntry) -> str:
    return f"{entry.answer} 来源 {entry.source_id}。"


def _asks_line_endpoints(question: str) -> bool:
    return ("线路" in question or "line" in question.lower()) and ("连接" in question or "哪两个" in question)


def _asks_n_minus_one(question: str) -> bool:
    return "n-1" in question.lower()


def _line_identifier(question: str) -> str | None:
    match = re.search(r"线路\s*(\d+)", question)
    if match is not None:
        return match.group(1)
    match = re.search(r"\bline\s+(\d+)\b", question, flags=re.IGNORECASE)
    return match.group(1) if match is not None else None


def _answer_line_endpoints(client: CapabilityClient, context_ref: str, line_id: str) -> str:
    line = client.invoke(
        "topology.branch.endpoints.get",
        {"context_ref": context_ref, "kind": "line", "namespace": "pandapower_index", "identifier": line_id},
    )
    return (
        f"线路 {line['branch']['alias']} 连接母线 {line['from_bus']['name']} 与 {line['to_bus']['name']}；"
        f"证据 {line['evidence_ref']}。"
    )


def _answer_powerflow(powerflow: dict[str, object]) -> str:
    loss = dict(powerflow["total_active_loss"])
    evidence = ", ".join(str(ref) for ref in powerflow["evidence_refs"])
    return (
        f"IEEE-39 交流潮流已收敛；总有功网损为 {float(loss['value']):.14f} {loss['unit']}，"
        f"结果 {powerflow['result_ref']}，证据 {evidence}。"
    )


def _answer_ranking(ranking: dict[str, object], powerflow: dict[str, object]) -> str:
    branches = list(ranking["branches"])
    parts = [
        f"线路 {branch['pandapower_index']} {float(branch['metric_value']):.2f}%"
        for branch in branches
    ]
    evidence = ", ".join(str(ref) for ref in powerflow["evidence_refs"])
    return (
        f"IEEE-39 负载率最高的 {len(branches)} 条线路为：{'; '.join(parts)}。"
        f"排序基于结果 {ranking['result_ref']}，证据 {evidence}。"
    )


def _answer_n_minus_one(result: dict[str, object], line_id: str) -> str:
    scenarios = list(result["scenarios"])
    scenario = dict(scenarios[0])
    violations = list(scenario["violations"])
    if violations:
        summary = f"发现 {len(violations)} 项越限"
    else:
        summary = "未发现所检查类型的越限"
    return (
        f"线路 {line_id} 的 N-1 静态安全校核状态为 {scenario['status']}，{summary}；"
        f"最大线路负载率 {float(scenario.get('max_loading_percent', 0.0)):.2f}%。"
        f"结果 {result['result_ref']}，证据 {scenario['evidence_ref']}。"
    )


def _answer_fault_ranking(result: dict[str, object]) -> str:
    scenarios = sorted(
        list(result["scenarios"]),
        key=lambda item: (len(item["violations"]), float(item.get("max_loading_percent", 0.0))),
        reverse=True,
    )
    parts = [
        (
            f"线路 {scenario['pandapower_index']} 越限 {len(scenario['violations'])} 项，"
            f"最大负载率 {float(scenario.get('max_loading_percent', 0.0)):.2f}%"
        )
        for scenario in scenarios
    ]
    evidence = ", ".join(str(ref) for ref in result["evidence_refs"])
    return f"关键线路故障分析排序：{'; '.join(parts)}。结果 {result['result_ref']}，证据 {evidence}。"
