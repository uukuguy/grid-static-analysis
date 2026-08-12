#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from grid_agent.contracts import AnswerEnvelope
from grid_agent.validation.cases import ValidationCase, load_cases
from grid_agent.validation.oracles import ORACLES


_OPERATION_CAPABILITIES = {
    "element.resolve": "model.element.get",
    "powerflow.run_ac": "analysis.powerflow.ac.run",
}


@dataclass(frozen=True)
class TraceSummary:
    capabilities: tuple[str, ...]
    tool_calls: int


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    suites = tuple(args.suite or ())
    case_ids = tuple(args.case_id or ())
    cases = _select_cases(load_cases(args.cases_root), suite=suites, case_id=case_ids)
    passed = 0

    for case in cases:
        record = _run_case(case, args.command_template, trace_template=args.trace_template, timeout_seconds=args.timeout_seconds)
        if record["passed"] is True:
            passed += 1
        _emit(record)

    summary = {"type": "summary", "total": len(cases), "passed": passed, "failed": len(cases) - passed}
    _emit(summary)
    return 0 if summary["failed"] == 0 else 1


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic grid-agent validation cases.")
    parser.add_argument("--cases-root", type=Path, default=Path("validation"))
    parser.add_argument("--suite", action="append")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--trace-template")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("command_template", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command_template and args.command_template[0] == "--":
        args.command_template = args.command_template[1:]
    if not args.command_template:
        parser.error("a command template is required after --")
    return args


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


def _run_case(
    case: ValidationCase,
    command_template: Sequence[str],
    *,
    trace_template: str | None,
    timeout_seconds: float,
) -> dict[str, object]:
    command = _format_template(command_template, case)
    errors: list[str] = []
    completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout_seconds)

    if completed.returncode != 0:
        errors.append(f"command exited with return code {completed.returncode}")

    answer = _parse_answer(completed.stdout, errors)
    if answer is not None:
        if answer.question_id != case.id:
            errors.append(f"answer question_id mismatch: expected {case.id}, got {answer.question_id}")
        evaluator = ORACLES.get(case.oracle.evaluator)
        if evaluator is None:
            errors.append(f"unknown oracle evaluator: {case.oracle.evaluator}")
        elif not evaluator(answer.answer_output, case.oracle.arguments):
            errors.append(f"oracle failed: {case.oracle.evaluator}")

    trace_path = Path(_format_template([trace_template], case)[0]) if trace_template else None
    trace = _load_trace(trace_path, errors) if trace_path is not None else None
    _check_requirements(case, trace, errors)

    return {
        "type": "case",
        "case_id": case.id,
        "passed": not errors,
        "returncode": completed.returncode,
        "oracle": case.oracle.evaluator,
        "errors": errors,
    }


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
    if trace.tool_calls > requirements.max_tool_calls:
        errors.append(f"tool call limit exceeded: {trace.tool_calls} > {requirements.max_tool_calls}")


def _load_trace(path: Path, errors: list[str]) -> TraceSummary | None:
    if not path.exists():
        errors.append(f"trace file not found: {path}")
        return None

    capabilities: list[str] = []
    tool_calls = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"trace line {line_number} is not valid JSON")
            continue
        capability = _event_capability(event)
        if capability is not None:
            capabilities.append(capability)
            tool_calls += 1
        elif _is_tool_event(event):
            tool_calls += 1
    return TraceSummary(capabilities=tuple(capabilities), tool_calls=tool_calls)


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


def _emit(record: Mapping[str, object]) -> None:
    print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    sys.exit(main())
