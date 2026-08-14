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


def test_continuous_analysis_reuses_powerflow_result_and_reports_context_lineage(
    scripted_analysis: ScriptedAnalysis,
) -> None:
    prompts = ("运行交流潮流", "筛选负载率最高的5条线路", "对最高负载线路开展N-1校核")
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

        assert len(answers) == 3
        assert [item["question_id"] for item in answers] == [turn.turn_id for turn in context.turns]
        assert (root / context.input.copied_path).read_text(encoding="utf-8") == expected_input
        assert context.input.source_path == str(scripted_analysis.tmp_path / "instructions.md.txt")
        assert context.input.copied_path == "input/instructions.md.txt"
        assert context.input.sha256 == sha256(expected_input.encode("utf-8")).hexdigest()
        assert context.input.instruction_count == len(prompts)
        assert scripted_analysis.pi_process_start_count == 1
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
        assert context.turns[1].consumed_refs == [powerflow_ref]
        assert context.turns[2].consumed_refs
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
        assert powerflow_ref not in report_text
        assert n1_ref not in report_text
        assert not any(item.get("type") in {"text_delta", "message_update"} for item in trace)
        assert AnalysisContextStore.replay(root / "context/context-events.jsonl") == context

        powerflow_start = _tool_start(trace, "grid_analysis_powerflow_ac")
        ranking_start = _tool_start(trace, "grid_result_branches_rank")
        n1_start = _tool_start(trace, "grid_analysis_contingency_n_minus_one")
        assert ranking_start["args"]["result_ref"] == powerflow_start["result"]["result_ref"]
        assert n1_start["args"]["context_ref"] == powerflow_start["result"]["context_ref"]
        assert n1_start["args"]["branch_refs"][0] in {
            branch["branch_ref"] for branch in ranking_start["result"]["branches"]
        }
        assert events[-1]["next_state_hash"] == context.state_hash
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
from pathlib import Path


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


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


def latest_reusable_result(capability):
    view = load_json(os.environ["GRID_AGENT_ANALYSIS_CONTEXT_VIEW"])
    matches = [item for item in view["reusable_results"] if item["capability"] == capability]
    if not matches:
        raise RuntimeError(f"context view has no reusable result for {{capability}}")
    return matches[-1]


def answer_first_turn():
    opened = grid("context.open", {{"model_id": "ieee39"}}, "call-001-open")
    powerflow = grid("analysis.powerflow.ac.run", {{"context_ref": opened["context_ref"]}}, "call-002-powerflow")
    STATE["context_ref"] = opened["context_ref"]
    STATE["powerflow_ref"] = powerflow["result_ref"]
    STATE["powerflow_evidence_refs"] = evidence_refs_for(powerflow)
    submit_answer(
        f"交流潮流已收敛，结果引用 {{powerflow['result_ref']}}。",
        [powerflow["result_ref"]],
        evidence_refs_for(powerflow),
        "call-003-submit",
    )


def answer_second_turn():
    reusable = latest_reusable_result("analysis.powerflow.ac.run")
    powerflow_ref = reusable["result_ref"]
    if STATE.get("powerflow_ref") and STATE["powerflow_ref"] != powerflow_ref:
        raise RuntimeError("context view did not preserve exact powerflow result_ref")
    ranking = grid(
        "result.branches.rank",
        {{"result_ref": powerflow_ref, "metric": "loading_percent", "direction": "descending", "limit": 5, "element_kind": "line"}},
        "call-004-ranking",
    )
    top_branch = ranking["branches"][0]["branch_ref"]
    STATE["ranking"] = ranking
    STATE["top_branch_ref"] = top_branch
    submit_answer(
        f"负载率最高线路为 {{top_branch}}，复用潮流结果 {{powerflow_ref}}。",
        [powerflow_ref],
        list(reusable["evidence_refs"]),
        "call-005-submit",
    )


def answer_third_turn():
    reusable = latest_reusable_result("analysis.powerflow.ac.run")
    powerflow_ref = reusable["result_ref"]
    ranking = STATE.get("ranking")
    if not ranking:
        raise RuntimeError("ranking result missing before N-1 turn")
    top_branch = ranking["branches"][0]["branch_ref"]
    n1 = grid(
        "analysis.contingency.n_minus_one.run",
        {{"context_ref": ranking["context_ref"], "branch_refs": [top_branch], "policy": "static-analysis-v1"}},
        "call-006-n1",
    )
    submit_answer(
        f"已对最高负载线路 {{top_branch}} 完成 N-1 校核，状态 {{n1['status']}}，复用潮流结果 {{powerflow_ref}}。",
        [n1["result_ref"]],
        evidence_refs_for(n1),
        "call-007-submit",
    )


marker = Path(os.environ["GRID_AGENT_WORKSPACE"]) / "pi" / "process-starts.txt"
previous_starts = marker.read_text(encoding="utf-8").strip() if marker.exists() else "0"
marker.write_text(str(int(previous_starts or "0") + 1) + "\\n", encoding="utf-8")
CATALOG = load_json(os.environ["GRID_AGENT_TOOL_CATALOG"])
STATE = {{}}
TURN_HANDLERS = [answer_first_turn, answer_second_turn, answer_third_turn]
turn_index = 0

for raw in sys.stdin:
    if not raw.strip():
        continue
    json.loads(raw)
    emit({{"type": "response", "command": "prompt", "success": True}})
    if turn_index >= len(TURN_HANDLERS):
        raise RuntimeError("received more prompts than scripted turns")
    TURN_HANDLERS[turn_index]()
    turn_index += 1
    emit({{"type": "agent_end", "messages": []}})
"""
