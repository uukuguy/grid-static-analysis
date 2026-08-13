from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from grid_agent.contracts import AnswerEnvelope


ROOT = Path(__file__).resolve().parents[4]


def test_scripted_pi_non_blocking_audit_keeps_topology_answer_in_run_and_batch_outputs(tmp_path: Path) -> None:
    question_id = "semantic-pi-line-11-e2e"
    runs_path = ROOT / "runs" / question_id
    shutil.rmtree(runs_path, ignore_errors=True)

    pi = tmp_path / "scripted-pi"
    pi.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, subprocess\n"
        "json.loads(input())\n"
        "catalog=json.load(open(os.environ['GRID_AGENT_TOOL_CATALOG'],encoding='utf-8'))\n"
        "by_cap={tool['capability']:tool['name'] for tool in catalog['tools']}\n"
        "def emit(payload): print(json.dumps(payload), flush=True)\n"
        "def grid(capability,args):\n"
        " name=by_cap[capability]\n"
        " emit({'type':'tool_execution_start','toolCallId':capability,'toolName':name,'args':args})\n"
        " req={'protocol':'grid-capability','protocol_version':'1.0','request_id':capability,'capability':capability,'arguments':args}\n"
        " r=subprocess.run(['gridctl','request','--workspace',os.environ['GRID_AGENT_WORKSPACE']],input=json.dumps(req)+'\\n',text=True,capture_output=True,check=True)\n"
        " response=json.loads(r.stdout)\n"
        " result=response.get('result') or {}\n"
        " refs=[]\n"
        " if isinstance(result.get('evidence_ref'),str): refs.append(result['evidence_ref'])\n"
        " refs.extend(result.get('evidence_refs') or [])\n"
        " emit({'type':'tool_result','toolCallId':capability,'toolName':name,'capability':capability,'ok':response.get('ok') is True,'result':result,'evidence_refs':refs})\n"
        " return result\n"
        "def guide(resource_id):\n"
        " index=json.load(open(os.environ['GRID_AGENT_GUIDE_INDEX'],encoding='utf-8'))\n"
        " emit({'type':'tool_execution_start','toolCallId':'guide-1','toolName':'grid_guide_open','args':{'resource_id':resource_id}})\n"
        " text=open(index['resources'][resource_id],encoding='utf-8').read()\n"
        " emit({'type':'tool_execution_end','toolCallId':'guide-1','toolName':'grid_guide_open','isError':False,'result':{'resource_id':resource_id}})\n"
        " return text\n"
        "emit({'type':'response','command':'prompt','success':True})\n"
        "guide('topology-analysis')\n"
        "opened=grid('context.open',{'model_id':'ieee39'})\n"
        "result=grid('topology.branch.endpoints.get',{'context_ref':opened['context_ref'],'kind':'line','namespace':'pandapower_index','identifier':'11'})\n"
        "ref=result['evidence_ref']\n"
        "draft={'answer_output':'线路11连接母线6与11。','result_refs':[opened['context_ref'],'asset:line:sha256:'+'a'*64],'claim_evidence_refs':[ref]}\n"
        "active_turn=os.environ.get('GRID_AGENT_ACTIVE_TURN')\n"
        "if active_turn:\n"
        " active=json.load(open(active_turn,encoding='utf-8'))\n"
        " draft.update({'turn_id':active['turn_id'],'turn_nonce':active['turn_nonce']})\n"
        "open(os.environ['GRID_AGENT_ANSWER_DRAFT'],'w',encoding='utf-8').write(json.dumps(draft,ensure_ascii=False))\n"
        "emit({'type':'tool_execution_start','toolCallId':'submit-1','toolName':'grid_submit_answer','args':{'answer_output':draft['answer_output']}})\n"
        "emit({'type':'tool_execution_end','toolCallId':'submit-1','toolName':'grid_submit_answer','isError':False,'result':{'answer_output':draft['answer_output']}})\n"
        "emit({'type':'agent_end'})\n",
        encoding="utf-8",
    )
    pi.chmod(0o755)

    try:
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                "packages/grid-agent",
                "grid-agent",
                "run",
                "--question-id",
                question_id,
                "IEEE-39节点系统中线路11连接哪两个母线?",
            ],
            cwd=ROOT,
            env={
                **os.environ,
                "GRID_AGENT_PI_COMMAND": str(pi),
                "GRID_AGENT_LLM_PROVIDER": "openai",
                "OPENAI_API_KEY": "test-only-secret",
            },
            text=True,
            capture_output=True,
            timeout=90,
        )

        assert completed.returncode == 0, completed.stderr
        envelope = AnswerEnvelope.model_validate_json(completed.stdout)
        assert envelope.answer_output == "线路11连接母线6与11。"
        audit = json.loads((runs_path / "answer-audit.json").read_text(encoding="utf-8"))
        assert len(audit["diagnostics"]) == 2
        assert all(diagnostic["severity"] == "warning" for diagnostic in audit["diagnostics"])
        events = [
            json.loads(line)["payload"]
            for line in (runs_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        legacy_query = "grid" + "_query"
        assert not any(event.get("toolName") in {"read", "bash", "shell", legacy_query} for event in events)
        assert not any(event.get("capability") == "analysis.powerflow.ac.run" for event in events)
        topology_results = [
            event
            for event in events
            if event.get("type") == "tool_result" and event.get("capability") == "topology.branch.endpoints.get"
        ]
        assert len(topology_results) == 1
        topology = topology_results[0]
        assert topology["result"]["branch"]["name"] == "11"
        assert topology["result"]["from_bus"]["name"] == "6"
        assert topology["result"]["to_bus"]["name"] == "11"
        assert topology["evidence_refs"]
        evidence_ref = topology["evidence_refs"][0]
        assert evidence_ref in json.loads((runs_path / "answer-draft.json").read_text(encoding="utf-8"))[
            "claim_evidence_refs"
        ]
        digest = evidence_ref.removeprefix("evidence:sha256:")
        assert (runs_path / "evidence/network-facts" / f"network-fact-{digest}.json").is_file()

        questions = tmp_path / "questions.txt"
        questions.write_text("IEEE-39节点系统中线路11连接哪两个母线?\n", encoding="utf-8")
        report = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                "packages/grid-agent",
                "grid-agent",
                "report",
                "--questions",
                str(questions),
            ],
            cwd=ROOT,
            env={
                **os.environ,
                "GRID_AGENT_PI_COMMAND": str(pi),
                "GRID_AGENT_LLM_PROVIDER": "openai",
                "OPENAI_API_KEY": "test-only-secret",
            },
            text=True,
            capture_output=True,
            timeout=90,
        )

        assert report.returncode == 0, report.stderr
        report_envelope = AnswerEnvelope.model_validate_json(report.stdout)
        report_root = ROOT / "runs" / report_envelope.question_id
        report_path = ROOT / report_envelope.answer_output
        report_text = report_path.read_text(encoding="utf-8")
        assert "线路11连接母线6与11。" in report_text
        jsonl_records = [json.loads(line) for line in (report_root / "output/answers.jsonl").read_text(encoding="utf-8").splitlines()]
        assert len(jsonl_records) == 1
        assert jsonl_records[0]["answer_output"] == "线路11连接母线6与11。"
        shutil.rmtree(report_root, ignore_errors=True)
    finally:
        shutil.rmtree(runs_path, ignore_errors=True)
