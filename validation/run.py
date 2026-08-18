#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pydantic import JsonValue, ValidationError

from grid_agent.application.workspace import RunWorkspace
from grid_agent.contracts import AnswerEnvelope
from grid_agent.knowledge.offline import answer_diagnostic, answer_information, plan_diagnostic
from grid_agent.simulator.client import GridctlClient, SimulatorCapabilityError
from grid_agent.simulator.locator import GridctlLocator
from grid_agent.validation.cases import ValidationCase, load_cases
from grid_agent.validation.corpus import AnswerCorpus, AnswerCorpusError, evaluate_corpus_trace, load_answer_corpus
from grid_agent.validation.oracles import ORACLES, ToolResultEvent


_OPERATION_CAPABILITIES = {
    "element.resolve": "model.element.get",
    "powerflow.run_ac": "analysis.powerflow.ac.run",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class TraceSummary:
    capabilities: tuple[str, ...]
    tool_calls: int
    result_events: tuple[ToolResultEvent, ...]

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        refs: list[str] = []
        for event in self.result_events:
            refs.extend(event.evidence_refs)
        return tuple(dict.fromkeys(refs))


@dataclass(frozen=True)
class CaseExecution:
    answer: AnswerEnvelope | None
    trace: TraceSummary | None
    run_path: Path | None
    returncode: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    metadata: Mapping[str, object]


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.mode is not None:
        return _main_mode(args)

    return _main_legacy(args)


def _main_legacy(args: argparse.Namespace) -> int:
    suites = tuple(args.suite or ())
    case_ids = tuple(args.case_id or ())
    cases = _select_cases(load_cases(args.cases_root), suite=suites, case_id=case_ids)
    answer_corpus = _load_required_corpus(cases, args.answer_corpus)
    passed = 0

    for case in cases:
        record = _run_case(
            case,
            args.command_template,
            trace_template=args.trace_template,
            timeout_seconds=args.timeout_seconds,
            answer_corpus=answer_corpus,
        )
        if record["passed"] is True:
            passed += 1
        _emit(record)

    summary = {"type": "summary", "total": len(cases), "passed": passed, "failed": len(cases) - passed}
    _emit(summary)
    return 0 if summary["failed"] == 0 else 1


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic grid-agent validation cases.")
    parser.add_argument("--cases-root", type=Path, default=Path("validation"))
    parser.add_argument("--mode", choices=("offline", "scripted-pi", "provider"))
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--answer-corpus",
        type=Path,
        default=_repo_root() / "docs/test_script/测试题目答案.jsonl",
    )
    parser.add_argument("--suite", action="append")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--trace-template")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("command_template", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command_template and args.command_template[0] == "--":
        args.command_template = args.command_template[1:]
    if args.mode is None and not args.command_template:
        parser.error("a command template is required after --")
    if args.mode is not None and args.command_template:
        parser.error("command templates are not supported with --mode")
    if args.mode is not None and args.report is None:
        parser.error("--report is required with --mode")
    if args.mode == "provider" and not args.provider:
        parser.error("--provider is required in provider mode")
    if args.mode in {"offline", "scripted-pi"} and args.provider:
        parser.error("--provider is only valid in provider mode")
    return args


def _main_mode(args: argparse.Namespace) -> int:
    suites = tuple(args.suite or ())
    if len(suites) != 1:
        raise SystemExit("--mode requires exactly one --suite")
    case_ids = tuple(args.case_id or ())
    cases = _select_cases(load_cases(args.cases_root), suite=suites, case_id=case_ids)
    answer_corpus = _load_required_corpus(cases, args.answer_corpus)
    records = [_run_mode_case(case, args, answer_corpus=answer_corpus) for case in cases]
    passed = sum(1 for record in records if record["passed"] is True)
    report = {
        "type": "validation_report",
        "version": "1.0",
        "mode": args.mode,
        "suite": suites[0],
        "provider": args.provider if args.mode == "provider" else None,
        "model": args.model if args.mode == "provider" else None,
        "summary": {"total": len(records), "passed": passed, "failed": len(records) - passed},
        "cases": records,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["summary"]["failed"] == 0 else 1


def _run_mode_case(
    case: ValidationCase,
    args: argparse.Namespace,
    *,
    answer_corpus: AnswerCorpus | None,
) -> dict[str, object]:
    started = time.monotonic()
    if args.mode == "offline":
        execution = _execute_offline_case(case, started_at=started, timeout_seconds=args.timeout_seconds)
    elif args.mode == "scripted-pi":
        execution = _execute_scripted_pi_case(case, started_at=started, timeout_seconds=args.timeout_seconds)
    elif args.mode == "provider":
        execution = _execute_provider_case(case, args, started_at=started, timeout_seconds=args.timeout_seconds)
    else:
        raise AssertionError(f"unsupported validation mode: {args.mode}")

    return _evaluate_execution(case, execution, answer_corpus=answer_corpus)


def _load_required_corpus(cases: Sequence[ValidationCase], path: Path) -> AnswerCorpus | None:
    if not any(case.oracle.kind == "semantic" for case in cases):
        return None
    try:
        return load_answer_corpus(path)
    except (OSError, AnswerCorpusError) as exc:
        raise SystemExit(f"semantic answer corpus unavailable: {path}: {exc}") from exc


def _select_cases(
    cases: Sequence[ValidationCase],
    *,
    suite: Sequence[str],
    case_id: Sequence[str],
) -> tuple[ValidationCase, ...]:
    selected = tuple(
        case
        for case in cases
        if (not suite or any(name in case.suites for name in suite)) and (not case_id or case.id in case_id)
    )
    if not selected:
        raise SystemExit("no validation cases matched the requested filters")
    return selected


class _RecordingClient:
    def __init__(self, client: GridctlClient) -> None:
        self.client = client
        self.events: list[ToolResultEvent] = []

    def invoke(self, capability: str, arguments: dict[str, object]) -> dict[str, object]:
        try:
            result = self.client.invoke(capability, arguments)
        except SimulatorCapabilityError as exc:
            error = dict(exc.error)
            self.events.append(
                ToolResultEvent(
                    capability=capability,
                    result={},
                    evidence_refs=_extract_evidence_refs(error),
                    ok=False,
                    error=cast(Mapping[str, JsonValue], error),
                )
            )
            raise
        self.events.append(
            ToolResultEvent(
                capability=capability,
                result=cast(Mapping[str, JsonValue], result),
                evidence_refs=_extract_evidence_refs(result),
            )
        )
        return result


def _execute_offline_case(
    case: ValidationCase,
    *,
    started_at: float,
    timeout_seconds: float,
) -> CaseExecution:
    answer = answer_information(case.question)
    trace: TraceSummary | None = None
    run_path: Path | None = None
    if answer is None:
        plan = plan_diagnostic(case.question)
        if isinstance(plan, str):
            answer = plan
        else:
            run_path = Path("runs") / case.id
            shutil.rmtree(run_path, ignore_errors=True)
            workspace = RunWorkspace.create(Path("runs"), run_id=case.id)
            client = _RecordingClient(
                GridctlClient(
                    executable=GridctlLocator(_repo_root()).resolve(),
                    workspace=workspace.root_path,
                    timeout_seconds=timeout_seconds,
                )
            )
            answer = answer_diagnostic(case.question, client)
            trace = TraceSummary(
                capabilities=tuple(event.capability for event in client.events),
                tool_calls=len(client.events),
                result_events=tuple(client.events),
            )
    envelope = AnswerEnvelope(question_id=case.id, answer_output=answer)
    return CaseExecution(
        answer=envelope,
        trace=trace,
        run_path=run_path,
        returncode=0,
        stdout=json.dumps(envelope.model_dump(), ensure_ascii=False),
        stderr="",
        duration_seconds=time.monotonic() - started_at,
        metadata={},
    )


def _execute_scripted_pi_case(
    case: ValidationCase,
    *,
    started_at: float,
    timeout_seconds: float,
) -> CaseExecution:
    if case.id == "topology-line-endpoints-001":
        return _execute_scripted_pi_cli_case(case, started_at=started_at, timeout_seconds=timeout_seconds)
    return _execute_scripted_static_case(case, started_at=started_at, timeout_seconds=timeout_seconds)


def _execute_scripted_static_case(
    case: ValidationCase,
    *,
    started_at: float,
    timeout_seconds: float,
) -> CaseExecution:
    run_path = Path("runs") / case.id
    shutil.rmtree(run_path, ignore_errors=True)
    workspace = RunWorkspace.create(Path("runs"), run_id=case.id)
    client = _RecordingClient(
        GridctlClient(
            executable=GridctlLocator(_repo_root()).resolve(),
            workspace=workspace.root_path,
            timeout_seconds=timeout_seconds,
        )
    )
    if case.oracle.kind == "semantic":
        answer = _execute_corpus_semantic_scenario(case, client)
        guide_event = ToolResultEvent(
            capability="grid_guide_open",
            result={"resource_id": "native-static-analyses"},
            evidence_refs=(),
        )
        events = (guide_event, *client.events)
        trace = TraceSummary(
            capabilities=tuple(event.capability for event in events),
            tool_calls=len(events),
            result_events=tuple(events),
        )
        envelope = AnswerEnvelope(question_id=case.id, answer_output=answer)
        return CaseExecution(
            answer=envelope,
            trace=trace,
            run_path=workspace.root_path,
            returncode=0,
            stdout=json.dumps(envelope.model_dump(), ensure_ascii=False),
            stderr="",
            duration_seconds=time.monotonic() - started_at,
            metadata={"corpus_id": case.oracle.arguments.get("corpus_id")},
        )
    guide_event = ToolResultEvent(
        capability="grid_guide_open",
        result={"resource_id": _guide_for_case(case.id)},
        evidence_refs=(),
    )
    opened = client.invoke("context.open", {"model_id": case.model or "ieee39"})
    context_ref = str(opened["context_ref"])

    if case.id == "static-line-lookup-by-alias-001":
        result = client.invoke(
            "model.element.get",
            {"context_ref": context_ref, "kind": "line", "namespace": "alias", "identifier": "pandapower:line:11"},
        )
        answer = f"resolved {result['asset_ref']}"
    elif case.id == "static-bus-listing-001":
        result = client.invoke(
            "model.dataset.query",
            {
                "context_ref": context_ref,
                "dataset": "network.buses",
                "select": ["kind", "index", "name", "vn_kv"],
                "sort": {"field": "index", "direction": "ascending"},
                "limit": 3,
            },
        )
        answer = f"listed {result['returned_row_count']} buses"
    elif case.id == "static-branch-dataset-schema-001":
        result = client.invoke("model.dataset.describe", {"context_ref": context_ref, "dataset": "network.branches"})
        answer = f"branch fields {len(result.get('fields', []))}"
    elif case.id == "static-components-001":
        result = client.invoke("topology.components.get", {"context_ref": context_ref})
        answer = f"components {result['component_count']}"
    elif case.id == "static-invalid-field-recovery-001":
        try:
            client.invoke(
                "model.dataset.query",
                {"context_ref": context_ref, "dataset": "network.branches", "select": ["not_a_field"]},
            )
        except SimulatorCapabilityError:
            pass
        answer = "typed invalid field recovery"
    elif case.id == "static-stale-result-ref-001":
        try:
            client.invoke(
                "result.branches.rank",
                {
                    "result_ref": "result:sha256:" + "0" * 64,
                    "metric": "loading_percent",
                    "direction": "descending",
                    "limit": 5,
                },
            )
        except SimulatorCapabilityError:
            pass
        answer = "typed stale result limitation"
    elif case.id == "static-evidence-mismatch-001":
        try:
            client.invoke("evidence.get", {"evidence_ref": "evidence:sha256:" + "0" * 64})
        except SimulatorCapabilityError:
            pass
        answer = "typed evidence limitation"
    elif case.id == "static-ac-non-convergence-001":
        evidence_ref = _write_synthetic_evidence(
            workspace.root_path,
            {
                "evidence_type": "powerflow_non_convergence",
                "capability_id": "analysis.powerflow.ac.run",
                "context_ref": context_ref,
                "reason": "validation injection",
            },
        )
        client.events.append(
            ToolResultEvent(
                capability="analysis.powerflow.ac.run",
                result={},
                evidence_refs=(evidence_ref,),
                ok=False,
                error={
                    "code": "powerflow_non_converged",
                    "retryable": False,
                    "allowed_recovery_actions": [
                        "inspect_network_diagnostics",
                        "change_solver_profile",
                        "report_non_convergence",
                    ],
                },
            )
        )
        answer = "typed non-convergence limitation"
    elif case.id == "static-n1-partial-failure-001":
        element = client.invoke(
            "model.element.get",
            {"context_ref": context_ref, "kind": "line", "namespace": "pandapower_index", "identifier": "11"},
        )
        result = client.invoke(
            "analysis.contingency.n_minus_one.run",
            {
                "context_ref": context_ref,
                "branch_refs": [str(dict(element["element"])["asset_ref"])],
            },
        )
        evidence_ref = _write_synthetic_evidence(
            workspace.root_path,
            {
                "evidence_type": "powerflow_non_convergence",
                "capability_id": "analysis.contingency.n_minus_one.run",
                "context_ref": context_ref,
                "reason": "validation injection",
            },
        )
        client.events[-1] = ToolResultEvent(
            capability="analysis.contingency.n_minus_one.run",
            result={
                "status": "partial",
                "constraint_evaluation": result["constraint_evaluation"],
                "scenarios": [
                    {"status": "succeeded", "pandapower_index": 11},
                    {"status": "non_converged", "pandapower_index": 21},
                ],
            },
            evidence_refs=tuple(result.get("evidence_refs", ())) + (evidence_ref,),
        )
        answer = "typed partial N-1 result"
    elif case.id == "static-sourced-risk-001":
        constrained = client.invoke(
            "model.revision.derive",
            {
                "context_ref": context_ref,
                "patches": [
                    {
                        "operation": "set",
                        "kind": "bus",
                        "selector": {"where": {}},
                        "values": {"min_vm_pu": 0.8, "max_vm_pu": 0.9},
                    },
                    {
                        "operation": "set",
                        "kind": "line",
                        "selector": {"where": {}},
                        "values": {"max_loading_percent": 1.0},
                    },
                ],
            },
        )
        powerflow = _run_validation_analysis(
            client,
            str(constrained["context_ref"]),
            "powerflow.ac",
            {},
        )
        violations = client.invoke(
            "analysis.result.violations.evaluate",
            {"result_ref": str(powerflow["result_ref"])},
        )
        risk = client.invoke(
            "analysis.result.risk.rank",
            {"result_ref": str(violations["result_ref"]), "limit": 5},
        )
        answer = f"ranked {len(risk['rankings'])} sourced risks"
    else:
        answer = "执行限制 / execution limitation: scripted validation case is not implemented"

    events = (guide_event, *client.events)
    trace = TraceSummary(
        capabilities=tuple(event.capability for event in events),
        tool_calls=len(events),
        result_events=tuple(events),
    )
    envelope = AnswerEnvelope(question_id=case.id, answer_output=answer)
    return CaseExecution(
        answer=envelope,
        trace=trace,
        run_path=workspace.root_path,
        returncode=0,
        stdout=json.dumps(envelope.model_dump(), ensure_ascii=False),
        stderr="",
        duration_seconds=time.monotonic() - started_at,
        metadata={},
    )


def _execute_corpus_semantic_scenario(case: ValidationCase, client: _RecordingClient) -> str:
    corpus_id = str(case.oracle.arguments["corpus_id"])
    if corpus_id == "T-A1":
        context_ref = _open_validation_model(client, "ieee39")
        client.invoke(
            "model.dataset.query",
            {
                "context_ref": context_ref,
                "dataset": "network.bus",
                "select": ["index"],
                "where": {"in_service": True},
                "limit": 200,
            },
        )
    elif corpus_id == "T-B1":
        context_ref = _open_validation_model(client, "ieee39")
        topology = _run_validation_analysis(client, context_ref, "topology.unsupplied", {})
        _query_validation_result(
            client,
            str(topology["result_ref"]),
            "result.res_unsupplied_bus",
            ["bus_index"],
        )
    elif corpus_id == "T-C1":
        context_ref = _open_validation_model(client, "ieee39")
        powerflow = _run_validation_analysis(client, context_ref, "powerflow.ac", {"algorithm": "nr"})
        _query_validation_result(
            client,
            str(powerflow["result_ref"]),
            "result.res_ext_grid",
            ["index", "p_mw"],
            where={"index": 0},
        )
    elif corpus_id == "T-D1":
        context_ref = _open_validation_model(client, "ieee39")
        client.invoke(
            "model.element.get",
            {
                "context_ref": context_ref,
                "kind": "line",
                "namespace": "pandapower_index",
                "identifier": "0",
            },
        )
        derived = client.invoke(
            "model.revision.derive",
            {
                "context_ref": context_ref,
                "patches": [
                    {
                        "operation": "in_service",
                        "kind": "line",
                        "selector": {"indices": [0]},
                        "value": False,
                    }
                ],
            },
        )
        derived_context = str(derived["context_ref"])
        topology = _run_validation_analysis(client, derived_context, "topology.unsupplied", {})
        _query_validation_result(
            client,
            str(topology["result_ref"]),
            "result.res_unsupplied_bus",
            ["bus_index"],
        )
        _run_validation_analysis(client, derived_context, "powerflow.dc", {})
    elif corpus_id == "T-E1":
        context_ref = _open_validation_model(client, "case9")
        _run_validation_analysis(client, context_ref, "opf.dc", {})
    elif corpus_id == "T-F1":
        created = client.invoke(
            "model.create",
            {
                "name": "validation-one-bus-short-circuit",
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
        )
        short_circuit = _run_validation_analysis(
            client,
            str(created["context_ref"]),
            "short_circuit.iec60909",
            {"bus": 0, "fault": "3ph", "case": "max"},
        )
        _query_validation_result(
            client,
            str(short_circuit["result_ref"]),
            "result.res_bus_sc",
            ["index", "ikss_ka", "skss_mw"],
            where={"index": 0},
        )
    elif corpus_id == "T-G1":
        context_ref = _open_validation_model(client, "ieee39")
        derived = client.invoke(
            "model.revision.derive",
            {
                "context_ref": context_ref,
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
        )
        client.invoke(
            "analysis.powerflow.ac.run",
            {"context_ref": str(derived["context_ref"]), "algorithm": "nr"},
        )
    else:
        raise ValueError(f"unknown semantic corpus scenario: {corpus_id}")
    return f"semantic validation completed for {corpus_id}"


def _open_validation_model(client: _RecordingClient, model_id: str) -> str:
    return str(client.invoke("context.open", {"model_id": model_id})["context_ref"])


def _run_validation_analysis(
    client: _RecordingClient,
    context_ref: str,
    operation: str,
    options: dict[str, object],
) -> dict[str, object]:
    return client.invoke(
        "analysis.run",
        {"context_ref": context_ref, "operation": operation, "options": options},
    )


def _query_validation_result(
    client: _RecordingClient,
    result_ref: str,
    dataset: str,
    select: list[str],
    *,
    where: dict[str, object] | None = None,
) -> dict[str, object]:
    arguments: dict[str, object] = {
        "result_ref": result_ref,
        "dataset": dataset,
        "select": select,
        "limit": 100,
    }
    if where is not None:
        arguments["where"] = where
    return client.invoke("result.dataset.query", arguments)


def _guide_for_case(case_id: str) -> str:
    if "dataset" in case_id or "lookup" in case_id or "bus" in case_id or "field" in case_id:
        return "network-elements"
    if "components" in case_id:
        return "topology-analysis"
    if "n1" in case_id:
        return "contingency-analysis"
    if "result" in case_id:
        return "result-query"
    if "evidence" in case_id:
        return "evidence-and-recovery"
    return "capability-map"


def _execute_scripted_pi_cli_case(
    case: ValidationCase,
    *,
    started_at: float,
    timeout_seconds: float,
) -> CaseExecution:
    run_path = Path("runs") / case.id
    shutil.rmtree(run_path, ignore_errors=True)
    with tempfile.TemporaryDirectory(prefix="grid-validation-pi-") as temp_dir:
        pi_path = Path(temp_dir) / "scripted-pi"
        pi_path.write_text(_scripted_topology_pi_source(), encoding="utf-8")
        pi_path.chmod(0o755)
        completed = subprocess.run(
            [
                "grid-agent",
                "run",
                "--question-id",
                case.id,
                case.question,
            ],
            cwd=_repo_root(),
            env={
                **os.environ,
                "GRID_AGENT_PI_COMMAND": str(pi_path),
                "GRID_AGENT_LLM_PROVIDER": "openai",
                "OPENAI_API_KEY": "validation-scripted-secret",
            },
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    answer = _parse_answer(completed.stdout, []) if completed.returncode == 0 else None
    trace_path = run_path / "events.jsonl"
    trace = _load_trace(trace_path, []) if trace_path.exists() else None
    return CaseExecution(
        answer=answer,
        trace=trace,
        run_path=run_path,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=time.monotonic() - started_at,
        metadata={},
    )


def _execute_provider_case(
    case: ValidationCase,
    args: argparse.Namespace,
    *,
    started_at: float,
    timeout_seconds: float,
) -> CaseExecution:
    credential_error = _provider_credential_error(args.provider)
    if credential_error is not None:
        return CaseExecution(
            answer=None,
            trace=None,
            run_path=None,
            returncode=None,
            stdout="",
            stderr=credential_error,
            duration_seconds=time.monotonic() - started_at,
            metadata={"provider": args.provider, "model": args.model, "credentials": "missing"},
        )

    run_path = Path("runs") / case.id
    shutil.rmtree(run_path, ignore_errors=True)
    command = [
        "grid-agent",
        "run",
        "--question-id",
        case.id,
        "--provider",
        args.provider,
    ]
    if args.model:
        command.extend(["--model", args.model])
    command.append(case.question)
    completed = subprocess.run(
        command,
        cwd=_repo_root(),
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
    answer = _parse_answer(completed.stdout, []) if completed.stdout.strip() else None
    trace_path = run_path / "events.jsonl"
    trace = _load_trace(trace_path, []) if trace_path.exists() else None
    return CaseExecution(
        answer=answer,
        trace=trace,
        run_path=run_path if run_path.exists() else None,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=time.monotonic() - started_at,
        metadata={
            "provider": args.provider,
            "model": args.model,
            "latency_seconds": time.monotonic() - started_at,
            "tokens": None,
            "cost": None,
        },
    )


def _provider_credential_error(provider: str) -> str | None:
    key_by_provider = {
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "minimax": "MINIMAX_API_KEY",
    }
    key_name = key_by_provider.get(provider)
    if key_name is None:
        return None
    if os.environ.get(key_name):
        return None
    return f"provider mode requires explicit credentials: {key_name}"


def _evaluate_execution(
    case: ValidationCase,
    execution: CaseExecution,
    *,
    answer_corpus: AnswerCorpus | None,
) -> dict[str, object]:
    envelope_errors: list[str] = []
    oracle_errors: list[str] = []
    capability_errors: list[str] = []
    evidence_errors: list[str] = []

    if execution.returncode not in (0, None):
        envelope_errors.append(f"command exited with return code {execution.returncode}")
    if execution.answer is None:
        envelope_errors.append("answer envelope missing")
    elif execution.answer.question_id != case.id:
        envelope_errors.append(f"answer question_id mismatch: expected {case.id}, got {execution.answer.question_id}")

    _check_requirements(case, execution.trace, capability_errors)
    _check_oracle(case, execution.answer, execution.trace, oracle_errors, answer_corpus=answer_corpus)
    _check_evidence(case, execution, evidence_errors)

    checks = {
        "envelope": not envelope_errors,
        "oracle": not oracle_errors,
        "capability_constraints": not capability_errors,
        "evidence": not evidence_errors,
    }
    errors = {
        "envelope": envelope_errors,
        "oracle": oracle_errors,
        "capability_constraints": capability_errors,
        "evidence": evidence_errors,
    }
    efficiency = execution.trace is None or execution.trace.tool_calls <= case.requirements.max_tool_calls
    return {
        "type": "case",
        "case_id": case.id,
        "passed": all(checks.values()),
        "oracle": case.oracle.evaluator,
        "checks": checks,
        "errors": errors,
        "scores": {
            "orchestration_completion": 1.0 if checks["envelope"] else 0.0,
            "semantic_correctness": 1.0 if checks["oracle"] else 0.0,
            "evidence": 1.0 if checks["evidence"] else 0.0,
            "efficiency": 1.0 if efficiency else 0.0,
        },
        "efficiency": {
            "tool_calls": execution.trace.tool_calls if execution.trace else 0,
            "advisory_max_tool_calls": case.requirements.max_tool_calls,
            "within_advisory_budget": efficiency,
        },
        "trace": {
            "capabilities": list(execution.trace.capabilities) if execution.trace else [],
            "tool_calls": execution.trace.tool_calls if execution.trace else 0,
        },
        "evidence_refs": list(execution.trace.evidence_refs) if execution.trace else [],
        "returncode": execution.returncode,
        "duration_seconds": round(execution.duration_seconds, 3),
        "metadata": dict(execution.metadata),
    }


def _run_case(
    case: ValidationCase,
    command_template: Sequence[str],
    *,
    trace_template: str | None,
    timeout_seconds: float,
    answer_corpus: AnswerCorpus | None,
) -> dict[str, object]:
    command = _format_template(command_template, case)
    errors: list[str] = []
    stdout = ""
    returncode: int | None = None
    try:
        completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout_seconds)
        stdout = completed.stdout
        returncode = completed.returncode
    except subprocess.TimeoutExpired:
        errors.append(f"command_timeout: exceeded {timeout_seconds:g} seconds")
    except OSError as exc:
        errors.append(_classify_os_error(exc, command))

    if returncode is not None and returncode != 0:
        errors.append(f"command exited with return code {returncode}")

    answer = _parse_answer(stdout, errors) if returncode is not None else None
    if answer is not None:
        if answer.question_id != case.id:
            errors.append(f"answer question_id mismatch: expected {case.id}, got {answer.question_id}")

    trace_path = Path(_format_template([trace_template], case)[0]) if trace_template else None
    trace = _load_trace(trace_path, errors) if trace_path is not None else None
    _check_requirements(case, trace, errors)
    _check_oracle(case, answer, trace, errors, answer_corpus=answer_corpus)

    return {
        "type": "case",
        "case_id": case.id,
        "passed": not errors,
        "returncode": returncode,
        "oracle": case.oracle.evaluator,
        "errors": errors,
    }


def _classify_os_error(exc: OSError, command: Sequence[str]) -> str:
    executable = command[0] if command else ""
    if isinstance(exc, FileNotFoundError):
        return f"command_os_error: executable not found: {executable}"
    return f"command_os_error: {exc.__class__.__name__}: {exc.strerror or str(exc)}"


def _parse_answer(stdout: str, errors: list[str]) -> AnswerEnvelope | None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        errors.append("answer envelope is not valid JSON")
        return None
    try:
        return AnswerEnvelope.model_validate(payload)
    except ValidationError as exc:
        errors.append(f"answer envelope failed contract validation: {exc.errors()[0]['msg']}")
        return None


def _check_requirements(case: ValidationCase, trace: TraceSummary | None, errors: list[str]) -> None:
    requirements = case.requirements
    if trace is None:
        if case.oracle.kind == "structured":
            return
        if requirements.requires_evidence:
            errors.append("required evidence trace was not supplied")
        return

    capabilities = set(trace.capabilities)
    missing = tuple(item for item in requirements.required_capabilities if item not in capabilities)
    forbidden = tuple(item for item in requirements.forbidden_capabilities if item in capabilities)
    if missing:
        errors.append("missing required capabilities: " + ", ".join(missing))
    if forbidden:
        errors.append("forbidden capabilities observed: " + ", ".join(forbidden))


def _check_oracle(
    case: ValidationCase,
    answer: AnswerEnvelope | None,
    trace: TraceSummary | None,
    errors: list[str],
    *,
    answer_corpus: AnswerCorpus | None,
) -> None:
    if case.oracle.kind == "semantic":
        if trace is None:
            errors.append("semantic_trace_missing")
            return
        if answer_corpus is None:
            errors.append("semantic_answer_corpus_missing")
            return
        if case.oracle.evaluator != "corpus_trace_matches":
            errors.append(f"unknown semantic oracle evaluator: {case.oracle.evaluator}")
            return
        errors.extend(
            evaluate_corpus_trace(
                trace.result_events,
                dict(case.oracle.arguments),
                answer_corpus,
            )
        )
        return
    evaluator = ORACLES.get(case.oracle.evaluator)
    if evaluator is None:
        errors.append(f"unknown oracle evaluator: {case.oracle.evaluator}")
        return

    if case.oracle.kind == "structured":
        required_capability = case.requirements.required_capabilities[0]
        if trace is None:
            errors.append("verification_trace_missing: " + required_capability)
            return

        candidates = tuple(event for event in trace.result_events if event.capability == required_capability)
        if not candidates:
            errors.append("verification_result_missing: " + required_capability)
        elif case.oracle.evaluator != "error_matches" and not any(event.ok is True for event in candidates):
            errors.append("verification_result_missing: " + required_capability)
        elif (
            case.requirements.requires_evidence
            and case.oracle.evaluator != "error_matches"
            and required_capability != "result.branches.rank"
            and not any(event.evidence_refs for event in candidates)
        ):
            errors.append("verification_evidence_missing: " + required_capability)
        elif not any(evaluator(event, case.oracle.arguments) for event in candidates):
            errors.append("structured_oracle_mismatch: " + case.oracle.evaluator)
        return

    if answer is not None and not evaluator(answer.answer_output, case.oracle.arguments):
        errors.append(f"oracle failed: {case.oracle.evaluator}")


def _load_trace(path: Path, errors: list[str]) -> TraceSummary | None:
    if not path.exists():
        errors.append(f"trace file not found: {path}")
        return None

    capabilities: list[str] = []
    result_events: list[ToolResultEvent] = []
    tool_calls = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"trace line {line_number} is not valid JSON")
            continue
        payload = _trace_payload(event)
        result_event = _tool_result_event(payload, line_number, errors)
        if result_event is not None:
            result_events.append(result_event)
        capability = _event_capability(payload)
        if capability is not None:
            capabilities.append(capability)
            tool_calls += 1
        elif _is_tool_event(payload):
            tool_calls += 1
    return TraceSummary(
        capabilities=tuple(capabilities),
        tool_calls=tool_calls,
        result_events=tuple(result_events),
    )


def _tool_result_event(value: object, line_number: int, errors: list[str]) -> ToolResultEvent | None:
    if not isinstance(value, Mapping) or value.get("event") != "tool_result":
        if not isinstance(value, Mapping) or value.get("type") != "tool_result":
            return None
    ok = value.get("ok")
    if ok is not True and ok is not False:
        return None

    capability = value.get("capability")
    result = value.get("result", {})
    error = value.get("error")
    evidence_refs = value.get("evidence_refs", [])
    if (
        not isinstance(capability, str)
        or not isinstance(result, Mapping)
        or not isinstance(evidence_refs, list)
        or not all(isinstance(reference, str) for reference in evidence_refs)
        or (error is not None and not isinstance(error, Mapping))
    ):
        errors.append(f"trace tool_result event is malformed at line {line_number}")
        return None

    return ToolResultEvent(
        capability=capability,
        result=cast(Mapping[str, JsonValue], result),
        evidence_refs=tuple(evidence_refs),
        ok=ok,
        error=cast(Mapping[str, JsonValue] | None, error),
    )


def _trace_payload(event: object) -> object:
    if isinstance(event, Mapping) and event.get("event") == "pi_event":
        payload = event.get("payload")
        if isinstance(payload, Mapping):
            return payload
    return event


def _event_capability(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    for key in ("capability", "operation", "tool_name"):
        item = value.get(key)
        if isinstance(item, str):
            return _OPERATION_CAPABILITIES.get(item, item)
    for nested_key in ("payload", "args"):
        nested = value.get(nested_key)
        if isinstance(nested, Mapping):
            capability = _event_capability(nested)
            if capability is not None:
                return capability
    tool_name = value.get("toolName")
    if isinstance(tool_name, str):
        return tool_name
    return None


def _is_tool_event(value: object) -> bool:
    return isinstance(value, Mapping) and str(value.get("event", value.get("type", ""))).startswith("tool")


def _format_template(values: Sequence[str | None], case: ValidationCase) -> list[str]:
    mapping = {
        "case_id": case.id,
        "question_id": case.id,
        "question": case.question,
        "model": case.model or "",
    }
    return [value.format(**mapping) for value in values if value is not None]


def _check_evidence(case: ValidationCase, execution: CaseExecution, errors: list[str]) -> None:
    if not case.requirements.requires_evidence:
        return
    if execution.trace is None:
        errors.append("required evidence trace was not supplied")
        return
    evidence_refs = execution.trace.evidence_refs
    if not evidence_refs:
        errors.append("verification_evidence_missing")
        return
    if execution.run_path is None:
        errors.append("evidence run path missing")
        return
    missing = [ref for ref in evidence_refs if _evidence_path(execution.run_path, ref) is None]
    if missing:
        errors.append("evidence not found in current run: " + ", ".join(missing))


def _evidence_path(run_path: Path, evidence_ref: str) -> Path | None:
    if not evidence_ref.startswith("evidence:sha256:"):
        return None
    digest = evidence_ref.removeprefix("evidence:sha256:")
    if len(digest) != 64:
        return None
    candidates = (
        run_path / "evidence" / "network-facts" / f"network-fact-{digest}.json",
        run_path / "evidence" / "analysis" / f"analysis-evidence-{digest}.json",
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


def _extract_evidence_refs(value: Mapping[str, object]) -> tuple[str, ...]:
    refs: list[str] = []
    single = value.get("evidence_ref")
    if isinstance(single, str):
        refs.append(single)
    many = value.get("evidence_refs")
    if isinstance(many, list):
        refs.extend(item for item in many if isinstance(item, str))
    return tuple(dict.fromkeys(refs))


def _write_synthetic_evidence(run_path: Path, document: Mapping[str, object]) -> str:
    body = dict(document)
    payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    path = run_path / "evidence" / "analysis" / f"analysis-evidence-{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload + "\n", encoding="utf-8")
    return f"evidence:sha256:{digest}"


def _scripted_topology_pi_source() -> str:
    return """#!/usr/bin/env python3
import json
import os
import subprocess

json.loads(input())

def emit(payload):
    print(json.dumps(payload, ensure_ascii=False), flush=True)

def grid(capability, args):
    request = {
        "protocol": "grid-capability",
        "protocol_version": "1.0",
        "request_id": capability,
        "capability": capability,
        "arguments": args,
    }
    completed = subprocess.run(
        ["gridctl", "request", "--workspace", os.environ["GRID_AGENT_WORKSPACE"]],
        input=json.dumps(request, ensure_ascii=False) + "\\n",
        text=True,
        capture_output=True,
        check=True,
    )
    response = json.loads(completed.stdout)
    result = response.get("result") or {}
    refs = []
    if isinstance(result.get("evidence_ref"), str):
        refs.append(result["evidence_ref"])
    refs.extend(result.get("evidence_refs") or [])
    emit({"type": "tool_result", "capability": capability, "ok": response.get("ok") is True, "result": result, "error": response.get("error"), "evidence_refs": refs})
    return result

def guide(resource_id):
    index = json.load(open(os.environ["GRID_AGENT_GUIDE_INDEX"], encoding="utf-8"))
    text = open(index["resources"][resource_id], encoding="utf-8").read()
    emit({"type": "tool_result", "capability": "grid_guide_open", "ok": True, "result": {"resource_id": resource_id, "text": text}, "evidence_refs": []})

emit({"type": "response", "command": "prompt", "success": True})
guide("topology-analysis")
opened = grid("context.open", {"model_id": "ieee39"})
result = grid("topology.branch.endpoints.get", {"context_ref": opened["context_ref"], "kind": "line", "namespace": "pandapower_index", "identifier": "11"})
ref = result["evidence_ref"]
answer = f"线路11连接母线{result['from_bus']['name']}与{result['to_bus']['name']}；证据 {ref}。"
draft = {"answer_output": answer, "result_refs": [], "claim_evidence_refs": [ref]}
open(os.environ["GRID_AGENT_ANSWER_DRAFT"], "w", encoding="utf-8").write(json.dumps(draft, ensure_ascii=False))
emit({"type": "tool_result", "capability": "grid_submit_answer", "ok": True, "result": draft, "evidence_refs": [ref]})
emit({"type": "agent_end"})
"""


def _emit(record: Mapping[str, object]) -> None:
    print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    sys.exit(main())
