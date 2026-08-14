from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from grid_agent.analysis.models import AnalysisContext
from grid_agent.analysis.store import AnalysisContextStore
from grid_agent.contracts import AnswerEnvelope
from grid_agent.trajectory.reader import RunEventReader


ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class ScriptedAnalysis:
    project_root: Path
    pi_path: Path
    artifact_root: Path
    tmp_path: Path

    @property
    def pi_process_start_count(self) -> int:
        total = 0
        for marker in self.artifact_root.glob("*/pi/process-starts.txt"):
            total += int(marker.read_text(encoding="utf-8").strip() or "0")
        return total

    def run(self, prompts: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        instructions_path = self.tmp_path / "instructions.md.txt"
        instructions_path.write_text("\n".join(prompts) + "\n", encoding="utf-8")
        return subprocess.run(
            [
                "uv",
                "run",
                "--project",
                "packages/grid-agent",
                "grid-agent",
                "analysis",
                "--instructions",
                str(instructions_path),
                "--artifact-root",
                str(self.artifact_root),
            ],
            cwd=self.project_root,
            env={
                **os.environ,
                "GRID_AGENT_PI_COMMAND": str(self.pi_path),
                "GRID_AGENT_LLM_PROVIDER": "openai",
                "OPENAI_API_KEY": "test-only-secret",
            },
            text=True,
            capture_output=True,
            timeout=180,
        )


@pytest.fixture
def scripted_analysis(tmp_path: Path) -> ScriptedAnalysis:
    artifact_root = ROOT / "runs" / f"task12-continuous-{tmp_path.name}"
    shutil.rmtree(artifact_root, ignore_errors=True)
    pi_path = tmp_path / "scripted-continuous-pi.py"
    pi_path.write_text(_SCRIPTED_PI, encoding="utf-8")
    pi_path.chmod(0o755)
    return ScriptedAnalysis(project_root=ROOT, pi_path=pi_path, artifact_root=artifact_root, tmp_path=tmp_path)


def test_continuous_analysis_generalizes_active_model_constraints_and_result_reuse(
    scripted_analysis: ScriptedAnalysis,
) -> None:
    prompts = (
        "载入 IEEE-39 并说明第11号线路的连接端",
        "这个网络自身给母线电压设置了怎样的上下界？",
        "执行交流潮流并给出有功损耗",
        "沿用刚才结果列出负载率最高的五条线路",
        "对其中首位支路进行单一停运分析，报告原始指标和有来源的约束判断",
    )
    completed = scripted_analysis.run(prompts)
    assert completed.returncode == 0, completed.stderr
    envelope = AnswerEnvelope.model_validate_json(completed.stdout)
    root = scripted_analysis.artifact_root / envelope.question_id
    try:
        expected_input = "\n".join(prompts) + "\n"
        answers = [json.loads(line) for line in (root / "output/answers.jsonl").read_text().splitlines()]
        context = AnalysisContext.model_validate_json((root / "context/analysis-context.json").read_text())
        trace = [json.loads(line)["payload"] for line in (root / "trace/events.jsonl").read_text().splitlines()]
        events = [
            json.loads(line)
            for line in (root / "context/context-events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        report_text = (root / "report.md").read_text(encoding="utf-8")

        assert len(answers) == 5
        assert [item["question_id"] for item in answers] == [turn.turn_id for turn in context.turns]
        assert (root / context.input.copied_path).read_text(encoding="utf-8") == expected_input
        assert context.input.source_path == str(scripted_analysis.tmp_path / "instructions.md.txt")
        assert context.input.copied_path == "input/instructions.md.txt"
        assert context.input.sha256 == sha256(expected_input.encode("utf-8")).hexdigest()
        assert context.input.instruction_count == len(prompts)
        assert scripted_analysis.pi_process_start_count == 1
        assert context.domain_state.model is not None
        assert context.domain_state.model.model_id == "ieee39"
        voltage_constraint = next(
            item for item in context.domain_state.constraints.values() if item.quantity == "bus.vm_pu"
        )
        assert voltage_constraint.lower == 0.94
        assert voltage_constraint.upper == 1.06
        assert voltage_constraint.source_kind == "model"
        powerflow_ref = next(
            result.result_ref for result in context.results.values() if result.capability == "analysis.powerflow.ac.run"
        )
        n1_ref = next(
            result.result_ref
            for result in context.results.values()
            if result.capability == "analysis.contingency.n_minus_one.run"
        )
        ranking = next(item for item in context.observations.values() if item.capability == "result.branches.rank")
        assert ranking.consumed_refs == [powerflow_ref]
        assert powerflow_ref in context.domain_state.calculations
        assert n1_ref in context.domain_state.calculations
        assert context.domain_state.scenarios
        assert context.turns[3].consumed_refs == [powerflow_ref]
        assert context.turns[4].consumed_refs
        for turn, answer in zip(context.turns, answers, strict=True):
            assert turn.answer_path is not None
            archived_answer_path = root / turn.answer_path
            assert archived_answer_path.is_file()
            archived_answer = json.loads(archived_answer_path.read_text(encoding="utf-8"))
            assert archived_answer["question_id"] == answer["question_id"]
            assert archived_answer["answer_output"] == answer["answer_output"]

        assert report_text.startswith("# 系统仿真分析报告")
        assert "## 本批次运行环境" in report_text
        assert report_text.count("### 回答") == len(prompts)
        assert report_text.count("### 实际分析过程") == len(prompts)
        assert report_text.count("### 仿真环境上下文") == len(prompts)
        assert report_text.count("详细执行轨迹") == len(prompts)
        for prompt in prompts:
            assert prompt in report_text
        for turn in context.turns:
            detail_trace = root / f"turns/{turn.ordinal:03d}/trace.md"
            assert detail_trace.is_file()
            assert "### 输入" in detail_trace.read_text(encoding="utf-8")
            section = report_text.split(f"## {turn.ordinal}. ", maxsplit=1)[1]
            assert section.index("### 回答") < section.index("### 仿真环境上下文")
        assert powerflow_ref not in report_text
        assert n1_ref not in report_text
        assert "policy" not in report_text.casefold()
        assert "模型约束数据" in report_text
        assert "读取活动模型内定义的约束" in report_text
        assert "线路负载约束：≤100 %（模型数据）" in report_text
        assert "变压器负载约束：≤100 %（模型数据）" in report_text
        assert "policy" not in json.dumps(trace, ensure_ascii=False).casefold()
        assert "policy" not in context.model_dump_json().casefold()
        assert not any(item.get("type") in {"text_delta", "message_update"} for item in trace)
        assert AnalysisContextStore.replay(root / "context/context-events.jsonl") == context

        powerflow_start = _tool_start(trace, "grid_analysis_powerflow_ac")
        constraints_start = _tool_start(trace, "grid_model_constraints_describe")
        ranking_start = _tool_start(trace, "grid_result_branches_rank")
        n1_start = _tool_start(trace, "grid_analysis_contingency_n_minus_one")
        assert ranking_start["args"]["result_ref"] == powerflow_start["result"]["result_ref"]
        assert constraints_start["args"]["context_ref"] == powerflow_start["result"]["context_ref"]
        assert n1_start["args"]["context_ref"] == powerflow_start["result"]["context_ref"]
        assert n1_start["args"]["branch_refs"][0] in {
            branch["branch_ref"] for branch in ranking_start["result"]["branches"]
        }
        assert events[-1]["next_state_hash"] == context.state_hash
    finally:
        shutil.rmtree(scripted_analysis.artifact_root, ignore_errors=True)


def test_scripted_analysis_writes_replayable_native_trajectory(
    scripted_analysis: ScriptedAnalysis,
) -> None:
    completed = scripted_analysis.run(("载入 IEEE-39 并说明第11号线路的连接端",))
    assert completed.returncode == 0, completed.stderr
    assert len(completed.stdout.splitlines()) == 1
    envelope = AnswerEnvelope.model_validate_json(completed.stdout)
    root = scripted_analysis.artifact_root / envelope.question_id
    try:
        prefix = RunEventReader(root / "events/run-events.jsonl").read_prefix()
        assert prefix.failure is None
        event_types = [event.event_type for event in prefix.events]
        assert event_types[0] == "analysis.started"
        assert event_types[-1] == "analysis.completed"
        assert "model.request.started" in event_types
        assert "tool.completed" in event_types
        assert "answer.submitted" in event_types

        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["events_path"] == "events/run-events.jsonl"
        assert manifest["trajectory_schema_version"] == "grid-run-event/1.0"

        request = json.loads(
            next((root / "requests").glob("*/input.json")).read_text(encoding="utf-8")
        )
        assert request["provider"] == "openai"
        assert request["model"] == "gpt-5.5"
        assert "test-only-secret" not in json.dumps(request)
        assert "test-only-secret" not in (root / "events/run-events.jsonl").read_text(
            encoding="utf-8"
        )

        tool_start = next(
            event for event in prefix.events if event.event_type == "tool.started"
        )
        assert tool_start.scope.turn_id is not None
        assert tool_start.scope.tool_call_id is not None
        native_path = (
            root
            / "tool-results"
            / tool_start.scope.turn_id
            / f"{tool_start.scope.tool_call_id}.json"
        )
        native_bytes = native_path.read_bytes()
        assert json.loads(native_bytes)["schema_version"] == "grid-tool-invocation/1.0"

        context = AnalysisContext.model_validate_json(
            (root / "context/analysis-context.json").read_text(encoding="utf-8")
        )
        compatibility_paths = {
            root / observation.path for observation in context.observations.values()
        }
        assert compatibility_paths
        assert all("compatibility" in path.parts for path in compatibility_paths)
        assert native_path not in compatibility_paths
        assert native_path.read_bytes() == native_bytes
        trace_page = (root / "turns/001/trace.md").read_text(encoding="utf-8")
        assert "compatibility" in trace_page
        assert "原始工具结果工件不可用" not in trace_page
    finally:
        shutil.rmtree(scripted_analysis.artifact_root, ignore_errors=True)


def test_analysis_stdout_contract_survives_native_capture(
    scripted_analysis: ScriptedAnalysis,
) -> None:
    completed = scripted_analysis.run(("载入 IEEE-39 并说明第11号线路的连接端",))
    assert completed.returncode == 0, completed.stderr
    try:
        assert len(completed.stdout.splitlines()) == 1
        assert set(json.loads(completed.stdout)) == {"question_id", "answer_output"}
        assert "trajectory" not in completed.stdout
    finally:
        shutil.rmtree(scripted_analysis.artifact_root, ignore_errors=True)


def _tool_start(trace: list[dict[str, Any]], tool_name: str) -> dict[str, Any]:
    for index, item in enumerate(trace):
        if item.get("type") == "tool_execution_start" and item.get("tool_name") == tool_name:
            result = next(
                candidate
                for candidate in trace[index + 1 :]
                if candidate.get("type") == "tool_result" and candidate.get("tool_name") == tool_name
            )
            return {**item, "result": result["result"]}
    raise AssertionError(f"missing traced tool start: {tool_name}")


_SCRIPTED_PI = f"""#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def capture_provider_request(prompt):
    global request_index
    requests_path = os.environ.get("GRID_AGENT_TRAJECTORY_REQUESTS")
    if requests_path is None:
        return
    request_index += 1
    turn = load_json(os.environ["GRID_AGENT_ACTIVE_TURN"])
    capture_state = load_json(os.environ["GRID_AGENT_TRAJECTORY_CAPTURE_STATE"])
    request_id = f"{{turn['turn_id']}}-r{{request_index:03d}}"
    request_path = Path(requests_path) / request_id / "input.json"
    request_path.parent.mkdir()
    request_path.write_text(
        json.dumps(
            {{
                "schema_version": "grid-model-request-input/1.0",
                "request_id": request_id,
                "request_index": request_index,
                "turn_id": turn["turn_id"],
                "provider": os.environ["GRID_AGENT_PROVIDER_ID"],
                "model": os.environ["GRID_AGENT_MODEL_ID"],
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "source_event_sequences": capture_state["source_event_sequences"],
                "context_revision": capture_state["context_revision"],
                "context_state_hash": capture_state["context_state_hash"],
                "provider_payload": {{
                    "model": os.environ["GRID_AGENT_MODEL_ID"],
                    "messages": [{{"role": "user", "content": prompt}}],
                    "tools": [],
                }},
            }},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def tool_name_for(capability):
    for tool in CATALOG["tools"]:
        if tool["capability"] == capability:
            return tool["name"]
    raise RuntimeError(f"capability not in tool catalog: {{capability}}")


def evidence_refs_for(result):
    refs = []
    if isinstance(result.get("evidence_ref"), str):
        refs.append(result["evidence_ref"])
    refs.extend(ref for ref in result.get("evidence_refs", []) if isinstance(ref, str))
    return list(dict.fromkeys(refs))


def grid(capability, args, call_id):
    tool_name = tool_name_for(capability)
    emit({{"type": "tool_execution_start", "toolCallId": call_id, "toolName": tool_name, "args": args}})
    request = {{
        "protocol": "grid-capability",
        "protocol_version": "1.0",
        "request_id": call_id,
        "capability": capability,
        "arguments": args,
    }}
    completed = subprocess.run(
        ["gridctl", "request", "--workspace", os.environ["GRID_AGENT_WORKSPACE"]],
        input=json.dumps(request, ensure_ascii=False) + "\\n",
        text=True,
        capture_output=True,
        check=True,
    )
    response = json.loads(completed.stdout)
    result = response.get("result") if isinstance(response.get("result"), dict) else {{}}
    details = {{
        "event": "tool_result",
        "capability": capability,
        "ok": response.get("ok") is True,
        "result": result,
        "evidence_refs": evidence_refs_for(result),
    }}
    if response.get("ok") is not True:
        details["error"] = response.get("error", {{"message": "gridctl request failed"}})
    emit({{
        "type": "tool_execution_end",
        "toolCallId": call_id,
        "toolName": tool_name,
        "isError": response.get("ok") is not True,
        "result": {{"details": details}},
    }})
    if response.get("ok") is not True:
        raise RuntimeError(f"{{capability}} failed: {{response.get('error')}}")
    return result


def submit_answer(answer_output, result_refs, claim_evidence_refs, call_id):
    active_turn = load_json(os.environ["GRID_AGENT_ACTIVE_TURN"])
    draft = {{
        "turn_id": active_turn["turn_id"],
        "turn_nonce": active_turn["turn_nonce"],
        "answer_output": answer_output,
        "result_refs": result_refs,
        "claim_evidence_refs": claim_evidence_refs,
    }}
    emit({{
        "type": "tool_execution_start",
        "toolCallId": call_id,
        "toolName": "grid_submit_answer",
        "args": {{"answer_output": answer_output, "result_refs": result_refs, "claim_evidence_refs": claim_evidence_refs}},
    }})
    Path(os.environ["GRID_AGENT_ANSWER_DRAFT"]).write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    emit({{
        "type": "tool_execution_end",
        "toolCallId": call_id,
        "toolName": "grid_submit_answer",
        "isError": False,
        "result": {{"answer_output": answer_output}},
    }})


def latest_reusable_calculation(kind):
    view = load_json(os.environ["GRID_AGENT_ANALYSIS_CONTEXT_VIEW"])
    matches = [item for item in view["reusable_calculations"] if item["kind"] == kind]
    if not matches:
        raise RuntimeError(f"context view has no reusable calculation for {{kind}}")
    return matches[-1]


def answer_first_turn():
    opened = grid("context.open", {{"model_id": "ieee39"}}, "call-001-open")
    endpoints = grid(
        "topology.branch.endpoints.get",
        {{"context_ref": opened["context_ref"], "kind": "line", "namespace": "pandapower_index", "identifier": "11"}},
        "call-002-endpoints",
    )
    STATE["context_ref"] = opened["context_ref"]
    submit_answer(
        f"第11号线路连接母线 {{endpoints['from_bus']['name']}} 与 {{endpoints['to_bus']['name']}}。",
        [],
        evidence_refs_for(endpoints),
        "call-003-submit",
    )


def answer_second_turn():
    view = load_json(os.environ["GRID_AGENT_ANALYSIS_CONTEXT_VIEW"])
    active_model = view.get("active_model")
    if not isinstance(active_model, dict) or active_model.get("model_id") != "ieee39":
        raise RuntimeError("continuous context did not expose the active IEEE-39 model")
    constraints = grid(
        "model.constraints.describe",
        {{"context_ref": active_model["context_ref"]}},
        "call-004-constraints",
    )
    voltage = next(item for item in constraints["constraints"] if item["quantity"] == "bus.vm_pu")
    if voltage["lower"] != 0.94 or voltage["upper"] != 1.06 or voltage["source"]["kind"] != "model":
        raise RuntimeError("voltage constraints were not sourced from the active model")
    submit_answer(
        f"该模型的母线电压上下界为 {{voltage['lower']}}–{{voltage['upper']}} {{voltage['unit']}}，来源为模型数据。",
        [],
        evidence_refs_for(constraints),
        "call-005-submit",
    )


def answer_third_turn():
    view = load_json(os.environ["GRID_AGENT_ANALYSIS_CONTEXT_VIEW"])
    active_model = view["active_model"]
    powerflow = grid(
        "analysis.powerflow.ac.run",
        {{"context_ref": active_model["context_ref"]}},
        "call-006-powerflow",
    )
    STATE["powerflow_ref"] = powerflow["result_ref"]
    loss = powerflow["total_active_loss"]
    submit_answer(
        f"交流潮流已收敛，有功损耗为 {{loss['value']}} {{loss['unit']}}。",
        [powerflow["result_ref"]],
        evidence_refs_for(powerflow),
        "call-007-submit",
    )


def answer_fourth_turn():
    reusable = latest_reusable_calculation("powerflow.ac")
    powerflow_ref = reusable["result_ref"]
    if powerflow_ref != STATE.get("powerflow_ref"):
        raise RuntimeError("context view did not preserve exact powerflow result_ref")
    ranking = grid(
        "result.branches.rank",
        {{"result_ref": powerflow_ref, "metric": "loading_percent", "direction": "descending", "limit": 5, "element_kind": "line"}},
        "call-008-ranking",
    )
    STATE["ranking"] = ranking
    submit_answer(
        "已沿用前序潮流结果列出负载率最高的五条线路。",
        [powerflow_ref],
        list(reusable["evidence_refs"]),
        "call-009-submit",
    )


def answer_fifth_turn():
    reusable = latest_reusable_calculation("powerflow.ac")
    ranking = STATE.get("ranking")
    if not ranking:
        raise RuntimeError("ranking result missing before N-1 turn")
    top_branch = ranking["branches"][0]["branch_ref"]
    n1 = grid(
        "analysis.contingency.n_minus_one.run",
        {{"context_ref": ranking["context_ref"], "branch_refs": [top_branch]}},
        "call-010-n1",
    )
    scenario = n1["scenarios"][0]
    submit_answer(
        f"首位支路停运场景状态 {{scenario['status']}}，最大负载率 {{scenario.get('max_loading_percent')}}%，约束来源 {{scenario['constraint_evaluation']['source']}}。",
        [n1["result_ref"]],
        evidence_refs_for(n1),
        "call-011-submit",
    )


marker = Path(os.environ["GRID_AGENT_WORKSPACE"]) / "pi" / "process-starts.txt"
previous_starts = marker.read_text(encoding="utf-8").strip() if marker.exists() else "0"
marker.write_text(str(int(previous_starts or "0") + 1) + "\\n", encoding="utf-8")
CATALOG = load_json(os.environ["GRID_AGENT_TOOL_CATALOG"])
STATE = {{}}
TURN_HANDLERS = [answer_first_turn, answer_second_turn, answer_third_turn, answer_fourth_turn, answer_fifth_turn]
turn_index = 0
request_index = 0

for raw in sys.stdin:
    if not raw.strip():
        continue
    prompt = json.loads(raw)
    capture_provider_request(prompt)
    emit({{"type": "response", "command": "prompt", "success": True}})
    if turn_index >= len(TURN_HANDLERS):
        raise RuntimeError("received more prompts than scripted turns")
    TURN_HANDLERS[turn_index]()
    turn_index += 1
    emit({{
        "type": "message_end",
        "message": {{
            "role": "assistant",
            "content": [{{"type": "text", "text": "scripted answer submitted"}}],
            "usage": {{"input": 1, "output": 1}},
            "stopReason": "stop",
        }},
    }})
    emit({{"type": "agent_end", "messages": []}})
"""
