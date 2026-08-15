"""Read-only, deterministic importer for the pre-native v0.2 run layout."""

from __future__ import annotations

import hashlib
import heapq
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from datetime import datetime, UTC
import re

from grid_agent.trajectory.canonical import canonical_json_bytes
from grid_agent.trajectory.events import Causation, ContextBoundary, EventRefs, EventSource, RunScope, ZERO_PREDECESSOR_HASH
from grid_agent.trajectory.replay import ImportedRunEvent, SourceCoordinate


SOURCE_RANK = {"manifest": 0, "context": 1, "trace": 2, "pi": 3, "turn": 4, "artifact": 5}


class LegacyImportError(RuntimeError):
    """The immutable historical layout is incomplete or internally contradictory."""


@dataclass(frozen=True, slots=True)
class LegacyDiagnostic:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class LegacyRecord:
    id: str
    source_kind: str
    source_sequence: int
    path: str
    digest: str
    event_type: str
    turn_id: str | None = None
    tool_call_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str | None = None
    parent_id: str | None = None

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, LegacyRecord):
            return NotImplemented
        return (SOURCE_RANK[self.source_kind], self.source_sequence, self.id) < (SOURCE_RANK[other.source_kind], other.source_sequence, other.id)


@dataclass(frozen=True, slots=True)
class ImportedReplay:
    analysis_id: str
    events: tuple[ImportedRunEvent, ...]
    source_fingerprint: str
    diagnostics: tuple[LegacyDiagnostic, ...]


def _json_lines(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LegacyImportError(f"invalid JSON in {path}:{number}: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise LegacyImportError(f"JSON object required in {path}:{number}")
        yield number, value


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_path(run_root: Path, path: Path) -> str:
    return path.relative_to(run_root).as_posix()


def _trace_fields(value: dict[str, Any]) -> tuple[str | None, dict[str, Any], str | None]:
    """Read both semantic trace envelopes actually emitted by v0.2."""
    payload = value.get("payload")
    payload = payload if isinstance(payload, dict) else value
    item_type = payload.get("type") or payload.get("event") or value.get("type") or value.get("event")
    if not isinstance(item_type, str):
        item_type = None
    call_id = payload.get("tool_call_id") or payload.get("toolCallId")
    return item_type, payload, call_id if isinstance(call_id, str) else None


def _stable_topological_order(records: Sequence[LegacyRecord], edges: Sequence[tuple[str, str]]) -> tuple[LegacyRecord, ...]:
    by_id = {record.id: record for record in records}
    if len(by_id) != len(records):
        raise LegacyImportError("legacy source contains duplicate record identifiers")
    incoming = {record.id: set() for record in records}
    outgoing = {record.id: set() for record in records}
    for parent, child in edges:
        if parent not in by_id or child not in by_id:
            continue
        incoming[child].add(parent)
        outgoing[parent].add(child)
    ready = [record for record in records if not incoming[record.id]]
    heapq.heapify(ready)
    ordered: list[LegacyRecord] = []
    while ready:
        record = heapq.heappop(ready)
        ordered.append(record)
        for child in sorted(outgoing[record.id]):
            incoming[child].remove(record.id)
            if not incoming[child]:
                heapq.heappush(ready, by_id[child])
    if len(ordered) != len(records):
        raise LegacyImportError("legacy source constraints contain a cycle")
    return tuple(ordered)


class LegacyV02Importer:
    """Normalize proven v0.2 lifecycle facts without manufacturing missing data."""

    def __init__(self, run_root: Path) -> None:
        self.run_root = Path(run_root)

    def import_run(self) -> ImportedReplay:
        manifest_path = self.run_root / "manifest.json"
        if not manifest_path.is_file():
            raise LegacyImportError("legacy run is missing manifest.json")
        try:
            manifest = json.loads(manifest_path.read_bytes())
        except json.JSONDecodeError as exc:
            raise LegacyImportError("invalid manifest.json") from exc
        analysis_id = manifest.get("analysis_id") if isinstance(manifest, dict) else None
        if not isinstance(analysis_id, str) or not analysis_id:
            raise LegacyImportError("manifest.json is missing analysis_id")
        files = tuple(sorted(path for path in self.run_root.rglob("*") if path.is_file()))
        source_fingerprint = hashlib.sha256(canonical_json_bytes({path.relative_to(self.run_root).as_posix(): _digest(path) for path in files})).hexdigest()
        records: list[LegacyRecord] = []
        edges: list[tuple[str, str]] = []
        diagnostics: list[LegacyDiagnostic] = []
        manifest_digest = _digest(manifest_path)
        records.append(LegacyRecord("manifest:1", "manifest", 1, "manifest.json", manifest_digest, "analysis.started"))

        turn_starts: dict[str, str] = {}
        turn_ends: dict[str, str] = {}
        tool_turns = {
            path.stem: path.parent.name
            for path in sorted((self.run_root / "tool-results").glob("*/*.json"))
        }
        # Pi's v0.2 session format records the current turn only in user-message
        # content.  It is a source fact, not an inferred request input.
        turn_windows: list[tuple[datetime, str]] = []
        for pi_path in sorted((self.run_root / "pi").glob("*.jsonl")):
            for _line, value in _json_lines(pi_path):
                message = value.get("message")
                if not isinstance(message, dict) or message.get("role") != "user":
                    continue
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                text = "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
                match = re.search(r'"turn_id"\s*:\s*"([^"]+)"', text)
                timestamp = value.get("timestamp")
                if match and isinstance(timestamp, int):
                    turn_windows.append((datetime.fromtimestamp(timestamp / 1000, UTC), match.group(1)))
                elif match and isinstance(timestamp, str):
                    try:
                        turn_windows.append((datetime.fromisoformat(timestamp.replace("Z", "+00:00")), match.group(1)))
                    except ValueError:
                        pass
        turn_windows.sort()

        def turn_at(timestamp: object) -> str | None:
            if not isinstance(timestamp, str):
                return None
            try:
                instant = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                return None
            known = [turn_id for start, turn_id in turn_windows if start <= instant]
            return known[-1] if known else None
        context_path = self.run_root / "context/context-events.jsonl"
        trace_records: dict[int, str] = {}
        if context_path.is_file():
            digest = _digest(context_path)
            previous_context_id: str | None = None
            for line, value in _json_lines(context_path):
                if value.get("analysis_id") != analysis_id:
                    raise LegacyImportError(f"context/context-events.jsonl:{line} has missing or mismatched analysis_id")
                if not isinstance(value.get("event_type"), str):
                    raise LegacyImportError(f"context/context-events.jsonl:{line} is missing event_type")
                if not isinstance(value.get("sequence"), int):
                    raise LegacyImportError(f"context/context-events.jsonl:{line} is missing sequence")
                kind = value.get("event_type")
                turn_id = value.get("turn_id") if isinstance(value.get("turn_id"), str) else None
                mapping = {"turn.started": "turn.started", "turn.completed": "turn.completed", "analysis.completed": "analysis.completed", "analysis.failed": "analysis.failed"}
                event_type = mapping.get(kind if isinstance(kind, str) else "", "context.projected")
                record = LegacyRecord(f"context:{line}", "context", line, "context/context-events.jsonl", digest, event_type, turn_id, payload={"ordinal": value.get("payload", {}).get("ordinal"), "revision": value.get("next_revision"), "state_hash": value.get("next_state_hash"), "after_state": value.get("payload", {})})
                records.append(record)
                if previous_context_id is not None:
                    edges.append((previous_context_id, record.id))
                previous_context_id = record.id
                if event_type == "turn.started" and turn_id:
                    turn_starts[turn_id] = record.id
                elif event_type == "turn.completed" and turn_id:
                    turn_ends[turn_id] = record.id
                trace_sequence = value.get("trace_sequence")
                if trace_sequence is not None:
                    if not isinstance(trace_sequence, int) or trace_sequence < 1:
                        raise LegacyImportError(f"context/context-events.jsonl:{line} has invalid trace_sequence")
                    trace_records[trace_sequence] = record.id
        else:
            diagnostics.append(LegacyDiagnostic("context-unavailable", "context ledger unavailable"))

        trace_path = self.run_root / "trace/events.jsonl"
        if trace_path.is_file():
            digest = _digest(trace_path)
            active_turn: str | None = None
            for line, value in _json_lines(trace_path):
                if not isinstance(value.get("sequence"), int):
                    raise LegacyImportError(f"trace/events.jsonl:{line} is missing sequence")
                item_type, payload, call_id = _trace_fields(value)
                if item_type is None:
                    raise LegacyImportError(f"trace/events.jsonl:{line} is missing event type")
                # Context records give an unambiguous turn only when they expose it;
                # otherwise a tool lifecycle remains observed with turn unavailable.
                if isinstance(value.get("turn_id"), str):
                    active_turn = value["turn_id"]
                else:
                    active_turn = turn_at(value.get("timestamp"))
                if isinstance(call_id, str) and call_id in tool_turns:
                    active_turn = tool_turns[call_id]
                if item_type == "tool_execution_start" and isinstance(call_id, str):
                    capability = payload.get("capability") or payload.get("tool_name") or payload.get("toolName")
                    records.append(LegacyRecord(f"trace:{line}", "trace", line, "trace/events.jsonl", digest, "tool.started", active_turn, call_id, {"capability": str(capability)}))
                elif item_type == "tool_result" and isinstance(call_id, str):
                    capability = payload.get("capability") or payload.get("tool_name") or payload.get("toolName")
                    refs = [item for item in (payload.get("evidence_refs") or []) if isinstance(item, str)]
                    result = payload.get("result")
                    if isinstance(result, dict) and isinstance(result.get("result_ref"), str):
                        refs.append(result["result_ref"])
                    context_ref = result.get("context_ref") if isinstance(result, dict) else None
                    records.append(LegacyRecord(f"trace:{line}", "trace", line, "trace/events.jsonl", digest, "tool.completed", active_turn, call_id, {"capability": str(capability), "ok": bool(payload.get("ok")), "context_ref": context_ref, "refs": refs}))
                else:
                    records.append(LegacyRecord(f"trace:{line}", "trace", line, "trace/events.jsonl", digest, "legacy.trace.event", active_turn, call_id, {"type": item_type}))
            for trace_sequence, context_id in trace_records.items():
                trace_id = f"trace:{trace_sequence}"
                if any(record.id == trace_id for record in records):
                    edges.append((trace_id, context_id))
                else:
                    diagnostics.append(LegacyDiagnostic("trace-sequence-unavailable", f"context trace_sequence {trace_sequence} has no trace record"))
        else:
            diagnostics.append(LegacyDiagnostic("trace-unavailable", "semantic trace unavailable"))

        def add_json_file(path: Path, source_kind: str, event_type: str, *, turn_id: str | None = None) -> None:
            relative = _source_path(self.run_root, path)
            try:
                value = json.loads(path.read_bytes())
            except json.JSONDecodeError as exc:
                raise LegacyImportError(f"invalid JSON in {relative}: {exc.msg}") from exc
            if not isinstance(value, dict):
                raise LegacyImportError(f"JSON object required in {relative}")
            records.append(LegacyRecord(f"{source_kind}:{relative}", source_kind, 1, relative, _digest(path), event_type, turn_id, payload={"available": True}))

        instruction_path = self.run_root / "input/instructions.md.txt"
        if instruction_path.is_file():
            records.append(LegacyRecord("artifact:input/instructions.md.txt", "artifact", 1, "input/instructions.md.txt", _digest(instruction_path), "legacy.instructions", payload={"available": True}))
        else:
            diagnostics.append(LegacyDiagnostic("instruction-unavailable", "instruction input unavailable"))

        pi_paths = tuple(sorted((self.run_root / "pi").glob("*.jsonl")))
        if pi_paths:
            for pi_path in pi_paths:
                digest = _digest(pi_path)
                for line, value in _json_lines(pi_path):
                    if not isinstance(value.get("type"), str):
                        raise LegacyImportError(f"{_source_path(self.run_root, pi_path)}:{line} is missing type")
                    records.append(LegacyRecord(f"pi:{pi_path.name}:{line}", "pi", line, _source_path(self.run_root, pi_path), digest, "legacy.pi.event", timestamp=value.get("timestamp") if isinstance(value.get("timestamp"), str) else None, payload={"type": value["type"]}))
        else:
            diagnostics.append(LegacyDiagnostic("pi-unavailable", "Pi session unavailable"))

        answers_path = self.run_root / "output/answers.jsonl"
        if answers_path.is_file():
            digest = _digest(answers_path)
            for line, value in _json_lines(answers_path):
                turn_id = value.get("question_id")
                if not isinstance(turn_id, str) or not isinstance(value.get("answer_output"), str):
                    raise LegacyImportError(f"output/answers.jsonl:{line} requires question_id and answer_output")
                records.append(LegacyRecord(f"turn:output:{line}", "turn", line, "output/answers.jsonl", digest, "legacy.answer.output", turn_id, payload={"available": True}))
        else:
            diagnostics.append(LegacyDiagnostic("answers-unavailable", "accepted answers unavailable"))
        turn_files = tuple(sorted((self.run_root / "turns").glob("*/answer*.json")))
        if turn_files:
            for path in turn_files:
                turn_id = path.parent.name
                event_type = "legacy.answer.audit" if path.name == "answer-audit.json" else "legacy.answer.draft" if path.name == "answer-draft.json" else "legacy.answer"
                add_json_file(path, "turn", event_type, turn_id=turn_id)
        else:
            diagnostics.append(LegacyDiagnostic("turn-artifacts-unavailable", "turn drafts and audits unavailable"))
        for path in sorted((self.run_root / "turns").glob("*/trace.md")):
            records.append(LegacyRecord(f"turn:{_source_path(self.run_root, path)}", "turn", 999998, _source_path(self.run_root, path), _digest(path), "legacy.turn.trace-page", path.parent.name, payload={"available": True}))

        for path in sorted((self.run_root / "tool-results").glob("*/*.json")):
            try:
                tool_result = json.loads(path.read_bytes())
            except json.JSONDecodeError as exc:
                raise LegacyImportError(f"invalid JSON in {_source_path(self.run_root, path)}: {exc.msg}") from exc
            if not isinstance(tool_result, dict) or not isinstance(tool_result.get("capability"), str) or not isinstance(tool_result.get("ok"), bool):
                raise LegacyImportError(f"{_source_path(self.run_root, path)} requires capability and ok")
            add_json_file(path, "artifact", "legacy.tool-result", turn_id=path.parent.name)
        for path in sorted((self.run_root / "evidence").glob("**/*.json")):
            add_json_file(path, "artifact", "legacy.artifact")
        report_path = self.run_root / "report.md"
        if report_path.is_file():
            records.append(LegacyRecord("artifact:report.md", "artifact", 999999, "report.md", _digest(report_path), "legacy.report", payload={"available": True}))
        else:
            diagnostics.append(LegacyDiagnostic("report-unavailable", "report unavailable"))

        # Tie each tool result to its start, and any known turn boundary.  No source
        # stream is globally assumed to be a historical total order.
        starts = {record.tool_call_id: record.id for record in records if record.event_type == "tool.started" and record.tool_call_id}
        for record in records:
            if record.event_type == "tool.completed" and record.tool_call_id in starts:
                edges.append((starts[record.tool_call_id], record.id))
            if record.turn_id and record.turn_id in turn_starts and record.event_type.startswith("tool."):
                edges.append((turn_starts[record.turn_id], record.id))
            if record.turn_id and record.turn_id in turn_ends and record.event_type.startswith("tool."):
                edges.append((record.id, turn_ends[record.turn_id]))
        ordered = _stable_topological_order(records, edges)
        events: list[ImportedRunEvent] = []
        sequences_by_record_id: dict[str, int] = {}
        edge_parents: dict[str, list[str]] = {}
        for parent, child in edges:
            edge_parents.setdefault(child, []).append(parent)
        previous_hash = ZERO_PREDECESSOR_HASH
        for sequence, record in enumerate(ordered, 1):
            explicit_parents = edge_parents.get(record.id, [])
            parent_sequence = next((sequences_by_record_id[parent] for parent in explicit_parents if parent in sequences_by_record_id), None)
            if parent_sequence is None:
                parent_sequence = next((event.sequence for event in events if event.source_coordinate.path == record.path and event.source_coordinate.sequence == record.source_sequence - 1), None)
            refs = record.payload.get("refs", [])
            event_payload = {key: value for key, value in record.payload.items() if key != "refs" and value is not None}
            content = {"analysis_id": analysis_id, "sequence": sequence, "event_type": record.event_type, "previous": previous_hash, "source": [record.path, record.source_sequence, record.digest], "payload": event_payload}
            import_hash = "sha256:" + hashlib.sha256(canonical_json_bytes(content)).hexdigest()
            event = ImportedRunEvent(analysis_id=analysis_id, sequence=sequence, timestamp=record.timestamp, event_type=record.event_type, import_previous_hash=previous_hash, import_hash=import_hash, source_coordinate=SourceCoordinate(path=record.path, sequence=record.source_sequence, sha256=record.digest), scope=RunScope(turn_id=record.turn_id, step_id=f"{record.turn_id}:s001" if record.turn_id else None, request_id=f"{record.turn_id}:r001" if record.turn_id else None, tool_call_id=record.tool_call_id), causation=Causation(parent_sequence=parent_sequence), source=EventSource(kind="observed", producer="legacy-v0.2-importer", integrity="importer-integrity"), context=ContextBoundary(after_revision=event_payload.get("revision")), refs=EventRefs(produced=tuple(ref for ref in refs if ref.startswith("result:")), evidence=tuple(ref for ref in refs if ref.startswith("evidence:"))), payload=event_payload)
            events.append(event)
            sequences_by_record_id[record.id] = sequence
            previous_hash = import_hash
        diagnostics.append(LegacyDiagnostic("missing-request-input", "model request input unavailable"))
        return ImportedReplay(analysis_id, tuple(events), source_fingerprint, tuple(diagnostics))


__all__ = ["ImportedReplay", "LegacyDiagnostic", "LegacyImportError", "LegacyRecord", "LegacyV02Importer", "SOURCE_RANK", "_stable_topological_order"]
