# Trajectory Event Spine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the authoritative typed, append-only, hash-chained `grid-run-event/1.0` spine, fail-closed replay, and immutable sidecar registry without changing runtime behavior yet.

**Architecture:** Focused `grid_agent.trajectory` modules own canonical JSON, typed event validation, the single event writer, replay verification, and sidecar admission. `AnalysisWorkspace` exposes the new directories, while the existing context ledger and semantic trace remain untouched until the native-capture plan connects them as compatibility projections.

**Tech Stack:** Python 3.12+, Pydantic 2.12, standard-library dataclasses/pathlib/json/hashlib/os/fsync, pytest 9, checked-in JSON Schema.

## Global Constraints

- The event schema is exactly `grid-run-event/1.0`; sequences start at 1 and are contiguous.
- Native timestamps are non-null UTC instants; the native writer never emits legacy-null timestamps.
- `previous_event_hash` uses `sha256:` plus 64 lowercase hex digits; sequence 1 uses `sha256:` plus 64 zeroes.
- `event_hash` hashes canonical UTF-8 JSON without the `event_hash` member and with one final newline.
- Canonical JSON sorts keys, preserves list order, rejects NaN/infinity, and contains no insignificant whitespace.
- `RunEventRecorder` is the only writer of `events/run-events.jsonl`; append and fsync complete before subscribers observe the event.
- Unknown required events, gaps, hash mismatches, invalid scopes, malformed JSON, and impossible envelope values stop trusted replay at the last valid prefix.
- Artifacts are atomically written, fsynced, and digest-verified before any event can reference them.
- Secret-bearing fields and hidden-reasoning keys are rejected before append; no silent field deletion is allowed.
- Existing Analysis context, stdout, evidence, report, and validation behavior remains unchanged in this plan.
- Use `apply_patch`, red/green TDD, focused tests first, and one atomic commit per task.

## File Map

### New production files

- `packages/grid-agent/src/grid_agent/trajectory/__init__.py` — public trajectory protocol exports.
- `packages/grid-agent/src/grid_agent/trajectory/canonical.py` — canonical JSON and digest helpers.
- `packages/grid-agent/src/grid_agent/trajectory/events.py` — envelope types, closed payload validation, scope invariants, and event hashing.
- `packages/grid-agent/src/grid_agent/trajectory/recorder.py` — single writer and durable subscriber publication.
- `packages/grid-agent/src/grid_agent/trajectory/reader.py` — fail-closed prefix replay and corruption diagnostics.
- `packages/grid-agent/src/grid_agent/trajectory/artifacts.py` — immutable JSON sidecar writing, verification, and safe paths.
- `scripts/update_trajectory_schemas.py` — deterministic schema generator.
- `schemas/grid-run-event-v1.schema.json` — checked-in normative envelope schema.
- `docs/architecture/trajectory-events.md` — protocol/operator contract.

### Modified production files

- `packages/grid-agent/src/grid_agent/analysis/workspace.py` — create `events/`, `requests/`, and `projections/` and expose their exact paths.

### Tests

- `packages/grid-agent/tests/trajectory/__init__.py`
- `packages/grid-agent/tests/trajectory/test_events.py`
- `packages/grid-agent/tests/trajectory/test_recorder.py`
- `packages/grid-agent/tests/trajectory/test_reader.py`
- `packages/grid-agent/tests/trajectory/test_artifacts.py`
- `packages/grid-agent/tests/contract/test_trajectory_docs.py`
- `packages/grid-agent/tests/analysis/test_workspace.py`

---

### Task 1: Canonical JSON and typed event envelope

**Files:**
- Create: `packages/grid-agent/src/grid_agent/trajectory/__init__.py`
- Create: `packages/grid-agent/src/grid_agent/trajectory/canonical.py`
- Create: `packages/grid-agent/src/grid_agent/trajectory/events.py`
- Create: `packages/grid-agent/tests/trajectory/__init__.py`
- Create: `packages/grid-agent/tests/trajectory/test_events.py`

**Interfaces:**
- Produces: `canonical_json_bytes(value: object) -> bytes` and `sha256_ref(value: bytes) -> str`.
- Produces: `RunScope`, `Causation`, `EventSource`, `ContextBoundary`, `EventRefs`, `EventDraft`, and `RunEvent`.
- Produces: `build_event(draft, *, analysis_id, sequence, timestamp, previous_event_hash) -> RunEvent`.
- Invariant: `EventDraft` validates its payload through the complete `PAYLOAD_MODELS` map before recorder code sees it.

- [ ] **Step 1: Write failing canonical/envelope tests**

```python
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from grid_agent.trajectory.canonical import canonical_json_bytes
from grid_agent.trajectory.events import EventDraft, RunEvent, RunScope, build_event


def test_build_event_is_canonical_and_hash_stable() -> None:
    draft = EventDraft(
        event_type="turn.started",
        scope=RunScope(turn_id="analysis-test-t001"),
        payload={"ordinal": 1, "instruction_sha256": "a" * 64},
    )
    event = build_event(
        draft,
        analysis_id="analysis-test",
        sequence=1,
        timestamp=datetime(2026, 8, 14, tzinfo=UTC),
        previous_event_hash="sha256:" + "0" * 64,
    )

    round_trip = RunEvent.model_validate_json(canonical_json_bytes(event.model_dump(mode="json")))
    assert round_trip == event
    assert event.schema_version == "grid-run-event/1.0"
    assert event.timestamp == "2026-08-14T00:00:00.000000Z"
    assert event.event_hash.startswith("sha256:")
    assert len(event.event_hash) == 71


def test_scope_rejects_request_without_step() -> None:
    with pytest.raises(ValidationError, match="request_id requires step_id"):
        RunScope(turn_id="analysis-test-t001", request_id="request-1")


def test_event_payload_is_closed_for_its_type() -> None:
    with pytest.raises(ValidationError, match="unexpected"):
        EventDraft(
            event_type="analysis.completed",
            payload={"completed_turns": 9, "total_turns": 9, "unexpected": True},
        )


def test_canonical_json_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError, match="Out of range float"):
        canonical_json_bytes({"value": float("nan")})
```

- [ ] **Step 2: Run the tests and confirm the import fails**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_events.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'grid_agent.trajectory'`.

- [ ] **Step 3: Implement canonical helpers and closed payload validation**

```python
# canonical.py
from __future__ import annotations

import json
from hashlib import sha256


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_ref(value: bytes) -> str:
    return f"sha256:{sha256(value).hexdigest()}"
```

```python
# events.py — keep every payload closed through this complete map
class EmptyPayload(StrictFrozenModel):
    pass


class AnalysisTerminalPayload(StrictFrozenModel):
    completed_turns: int = Field(ge=0)
    total_turns: int = Field(ge=0)


class ErrorPayload(StrictFrozenModel):
    error_type: str
    message: str


class TurnStartedPayload(StrictFrozenModel):
    ordinal: int = Field(ge=1)
    instruction_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class TurnTerminalPayload(StrictFrozenModel):
    status: Literal["success", "failed"]
    duration_seconds: float | None = Field(default=None, ge=0)


class ModelRequestPayload(StrictFrozenModel):
    artifact_ref: str
    request_index: int = Field(ge=1)


class ModelResponsePayload(StrictFrozenModel):
    artifact_ref: str
    stop_reason: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    ttft_seconds: float | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)


class RetryPayload(StrictFrozenModel):
    attempt: int = Field(ge=1)
    max_attempts: int = Field(ge=1)
    delay_seconds: float | None = Field(default=None, ge=0)
    message: str | None = None


class ToolPayload(StrictFrozenModel):
    capability: str
    artifact_ref: str | None = None
    ok: bool | None = None


class DecisionPayload(StrictFrozenModel):
    intent: str = Field(min_length=1, max_length=500)
    decision: str = Field(min_length=1, max_length=500)
    next_action: str = Field(min_length=1, max_length=500)


class ClaimPayload(StrictFrozenModel):
    submission_id: str
    statement: str = Field(min_length=1, max_length=1000)
    category: Literal["topology", "constraint", "numerical_result", "risk_judgment", "offline_information"]
    result_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


class ContextPayload(StrictFrozenModel):
    revision: int = Field(ge=0)
    state_hash: str
    artifact_ref: str | None = None


class AnswerPayload(StrictFrozenModel):
    submission_id: str
    artifact_ref: str
    result_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


class DiagnosticPayload(StrictFrozenModel):
    severity: Literal["info", "warning", "error"]
    category: str
    message: str


PAYLOAD_MODELS: dict[str, type[StrictFrozenModel]] = {
    "analysis.started": EmptyPayload,
    "analysis.completed": AnalysisTerminalPayload,
    "analysis.failed": ErrorPayload,
    "turn.started": TurnStartedPayload,
    "turn.completed": TurnTerminalPayload,
    "turn.failed": ErrorPayload,
    "step.started": EmptyPayload,
    "step.completed": EmptyPayload,
    "step.failed": ErrorPayload,
    "model.request.started": ModelRequestPayload,
    "model.response.completed": ModelResponsePayload,
    "model.response.failed": ErrorPayload,
    "model.retry.scheduled": RetryPayload,
    "model.retry.started": RetryPayload,
    "model.retry.exhausted": RetryPayload,
    "tool.started": ToolPayload,
    "tool.completed": ToolPayload,
    "tool.failed": ToolPayload,
    "business.decision.declared": DecisionPayload,
    "business.claim.declared": ClaimPayload,
    "context.projected": ContextPayload,
    "context.injected": ContextPayload,
    "answer.submitted": AnswerPayload,
    "answer.rejected": ErrorPayload,
    "audit.diagnostic.recorded": DiagnosticPayload,
}
```

Implement `EventDraft.model_validator(mode="after")` to replace `payload` with `PAYLOAD_MODELS[event_type].model_validate(payload).model_dump(mode="json")`. Implement `RunScope.model_validator` to enforce the turn → step → request → tool-call nesting. `build_event` formats UTC with six fractional digits and `Z`, builds the event without `event_hash`, hashes its canonical dump, then validates the final `RunEvent`.

- [ ] **Step 4: Run focused tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_events.py -q`

Expected: all canonical, scope, source, refs, payload, timestamp, and hash tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/trajectory packages/grid-agent/tests/trajectory
git commit -m "feat: define typed trajectory events"
```

### Task 2: Single durable recorder and fail-closed reader

**Files:**
- Create: `packages/grid-agent/src/grid_agent/trajectory/recorder.py`
- Create: `packages/grid-agent/src/grid_agent/trajectory/reader.py`
- Create: `packages/grid-agent/tests/trajectory/test_recorder.py`
- Create: `packages/grid-agent/tests/trajectory/test_reader.py`

**Interfaces:**
- Consumes: `EventDraft`, `build_event`, and an exact `events_path`.
- Produces: `RunEventRecorder(events_path, analysis_id, *, secret_values=(), subscribers=())`, `.append(draft) -> RunEvent`, and `.close() -> None`.
- Produces: `RunEventReader(events_path).read_prefix() -> ReplayPrefix` where `ReplayPrefix.events` is the trusted tuple and `ReplayPrefix.failure` describes the first invalid line.
- Invariant: subscriber exceptions do not alter the log; recorder write/fsync failure raises `RecorderIntegrityError` and permanently closes the recorder.

- [ ] **Step 1: Write failing recorder/reader tests**

```python
def test_recorder_appends_fsyncs_then_publishes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real_fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (calls.append("fsync"), real_fsync(fd))[1])
    recorder = RunEventRecorder(
        tmp_path / "events/run-events.jsonl",
        "analysis-test",
        subscribers=(lambda event: calls.append(f"publish:{event.sequence}"),),
    )

    first = recorder.append(EventDraft(event_type="analysis.started", payload={}))
    second = recorder.append(
        EventDraft(event_type="turn.started", scope=RunScope(turn_id="analysis-test-t001"), payload={"ordinal": 1, "instruction_sha256": "a" * 64})
    )

    assert calls == ["fsync", "publish:1", "fsync", "publish:2"]
    assert second.previous_event_hash == first.event_hash
    assert RunEventReader(recorder.events_path).read_prefix().events == (first, second)


def test_reader_stops_at_first_hash_mismatch(tmp_path: Path) -> None:
    path = write_three_valid_events(tmp_path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[1]["payload"]["ordinal"] = 99
    path.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows))

    prefix = RunEventReader(path).read_prefix()

    assert [event.sequence for event in prefix.events] == [1]
    assert prefix.failure is not None
    assert prefix.failure.line_number == 2
    assert prefix.failure.code == "event_hash_mismatch"


def test_recorder_rejects_secret_and_reasoning_fields(tmp_path: Path) -> None:
    recorder = RunEventRecorder(tmp_path / "events.jsonl", "analysis-test", secret_values={"sk-secret"})
    with pytest.raises(RecorderIntegrityError, match="prohibited content"):
        recorder.append(EventDraft(event_type="audit.diagnostic.recorded", payload={"severity": "error", "category": "provider", "message": "token=sk-secret"}))
    assert not recorder.events_path.exists()
```

- [ ] **Step 2: Run and confirm failures**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_recorder.py packages/grid-agent/tests/trajectory/test_reader.py -q`

Expected: FAIL because `recorder.py` and `reader.py` do not exist.

- [ ] **Step 3: Implement recorder durability and replay diagnostics**

```python
class RunEventRecorder:
    def append(self, draft: EventDraft) -> RunEvent:
        if self._closed:
            raise RecorderIntegrityError("trajectory recorder is closed")
        self._reject_prohibited_content(draft.model_dump(mode="json"))
        event = build_event(
            draft,
            analysis_id=self.analysis_id,
            sequence=self._next_sequence,
            timestamp=datetime.now(UTC),
            previous_event_hash=self._previous_hash,
        )
        try:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            with self.events_path.open("ab") as stream:
                stream.write(canonical_json_bytes(event.model_dump(mode="json")))
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            self._closed = True
            raise RecorderIntegrityError(f"trajectory append failed: {exc}") from exc
        self._next_sequence += 1
        self._previous_hash = event.event_hash
        for subscriber in self._subscribers:
            try:
                subscriber(event)
            except Exception as exc:
                self._subscriber_failures.append(f"{type(exc).__name__}: {exc}")
        return event
```

```python
@dataclass(frozen=True, slots=True)
class ReplayFailure:
    line_number: int
    code: Literal[
        "malformed_json", "invalid_event", "sequence_gap",
        "previous_hash_mismatch", "event_hash_mismatch", "unknown_event",
    ]
    message: str


@dataclass(frozen=True, slots=True)
class ReplayPrefix:
    events: tuple[RunEvent, ...]
    failure: ReplayFailure | None


class RunEventReader:
    def read_prefix(self) -> ReplayPrefix:
        trusted: list[RunEvent] = []
        previous = "sha256:" + "0" * 64
        for line_number, raw in enumerate(self.events_path.read_bytes().splitlines(), start=1):
            try:
                event = RunEvent.model_validate_json(raw)
            except (ValidationError, ValueError) as exc:
                return ReplayPrefix(tuple(trusted), ReplayFailure(line_number, "invalid_event", str(exc)))
            if event.sequence != line_number:
                return ReplayPrefix(tuple(trusted), ReplayFailure(line_number, "sequence_gap", f"expected {line_number}, got {event.sequence}"))
            if event.previous_event_hash != previous:
                return ReplayPrefix(tuple(trusted), ReplayFailure(line_number, "previous_hash_mismatch", "previous hash does not match trusted prefix"))
            if recompute_event_hash(event) != event.event_hash:
                return ReplayPrefix(tuple(trusted), ReplayFailure(line_number, "event_hash_mismatch", "event content does not match event_hash"))
            trusted.append(event)
            previous = event.event_hash
        return ReplayPrefix(tuple(trusted), None)
```

Distinguish JSON decoding from Pydantic validation in the final reader so error codes match the declared union. Reject blank lines and unknown non-ignorable event types. Add test injection for short writes and `os.fsync` failure; both must close the recorder and prevent a later append.

- [ ] **Step 4: Run focused tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_recorder.py packages/grid-agent/tests/trajectory/test_reader.py -q`

Expected: all ordering, fsync, subscriber, corruption-prefix, unknown-event, and permanent-failure tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/trajectory/recorder.py packages/grid-agent/src/grid_agent/trajectory/reader.py packages/grid-agent/tests/trajectory/test_recorder.py packages/grid-agent/tests/trajectory/test_reader.py
git commit -m "feat: persist and replay trajectory spine"
```

### Task 3: Immutable sidecar registry

**Files:**
- Create: `packages/grid-agent/src/grid_agent/trajectory/artifacts.py`
- Create: `packages/grid-agent/tests/trajectory/test_artifacts.py`

**Interfaces:**
- Produces: `ArtifactPointer(ref, kind, relative_path, sha256, size_bytes)`.
- Produces: `ImmutableArtifactRegistry(run_root).write_json(kind, identity, payload) -> ArtifactPointer`, `.register_existing(kind, identity, path) -> ArtifactPointer`, and `.verify(pointer) -> Path`.
- Allowed kinds and directories: `request-input -> requests/{identity}/input.json`, `model-response -> requests/{identity}/response.json`, `answer -> turns/{identity}/answer.json`, and existing registered result/evidence/tool-result documents.
- Invariant: `identity` matches `^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$`; resolved paths stay inside the real run root and never traverse symlinks.

- [ ] **Step 1: Write failing artifact tests**

```python
def test_registry_writes_once_and_verifies_digest(tmp_path: Path) -> None:
    registry = ImmutableArtifactRegistry(tmp_path / "runs/analysis-test")
    pointer = registry.write_json("request-input", "analysis-test-t001-r001", {"messages": [], "tools": []})

    assert pointer.relative_path == "requests/analysis-test-t001-r001/input.json"
    assert pointer.ref == f"artifact:sha256:{pointer.sha256}"
    assert registry.verify(pointer).read_text(encoding="utf-8").endswith("\n")
    assert registry.write_json("request-input", "analysis-test-t001-r001", {"messages": [], "tools": []}) == pointer


def test_registry_rejects_overwrite_with_different_content(tmp_path: Path) -> None:
    registry = ImmutableArtifactRegistry(tmp_path / "run")
    registry.write_json("request-input", "request-1", {"messages": []})
    with pytest.raises(ArtifactIntegrityError, match="different content"):
        registry.write_json("request-input", "request-1", {"messages": [{"role": "user"}]})


def test_registry_registers_exact_preexisting_bytes(tmp_path: Path) -> None:
    registry = ImmutableArtifactRegistry(tmp_path / "run")
    path = tmp_path / "run/requests/request-1/input.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"provider_payload":{"messages":[]}}\n')

    pointer = registry.register_existing("request-input", "request-1", path)

    assert registry.verify(pointer).read_bytes() == b'{"provider_payload":{"messages":[]}}\n'


@pytest.mark.parametrize("identity", ["../escape", "/absolute", "a/b", "a\\b"])
def test_registry_rejects_unsafe_identity(tmp_path: Path, identity: str) -> None:
    with pytest.raises(ArtifactIntegrityError, match="identity"):
        ImmutableArtifactRegistry(tmp_path / "run").write_json("request-input", identity, {})
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_artifacts.py -q`

Expected: FAIL because `ImmutableArtifactRegistry` is undefined.

- [ ] **Step 3: Implement atomic immutable writes**

```python
KIND_LAYOUT: dict[str, tuple[str, str]] = {
    "request-input": ("requests/{identity}", "input.json"),
    "model-response": ("requests/{identity}", "response.json"),
    "answer": ("turns/{identity}", "answer.json"),
}


def _write_bytes_atomic(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    with temporary.open("xb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


class ImmutableArtifactRegistry:
    def write_json(self, kind: str, identity: str, payload: object) -> ArtifactPointer:
        if kind not in KIND_LAYOUT or not IDENTITY_PATTERN.fullmatch(identity):
            raise ArtifactIntegrityError("artifact kind or identity is not registered")
        directory, filename = KIND_LAYOUT[kind]
        path = self.run_root / directory.format(identity=identity) / filename
        value = canonical_json_bytes(payload)
        digest = sha256(value).hexdigest()
        if path.exists():
            if path.read_bytes() != value:
                raise ArtifactIntegrityError("artifact path already contains different content")
        else:
            _write_bytes_atomic(path, value)
        pointer = ArtifactPointer(
            ref=f"artifact:sha256:{digest}",
            kind=kind,
            relative_path=path.relative_to(self.run_root).as_posix(),
            sha256=digest,
            size_bytes=len(value),
        )
        self.verify(pointer)
        return pointer
```

`register_existing` requires the exact path generated by `KIND_LAYOUT`, reads but never rewrites its bytes, rejects symlinks/non-regular files, and returns their content-addressed pointer. `verify` resolves the run root and artifact parent, rejects any resolved path outside the run root, rejects non-regular files, recomputes size/digest, and returns the verified path. Add tests for a tampered file and a symlinked request directory.

- [ ] **Step 4: Run focused tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_artifacts.py -q`

Expected: all immutability, exact-byte registration, idempotency, tamper, traversal, absolute-path, and symlink tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/trajectory/artifacts.py packages/grid-agent/tests/trajectory/test_artifacts.py
git commit -m "feat: register immutable trajectory artifacts"
```

### Task 4: Workspace paths, normative schema, and protocol documentation

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/analysis/workspace.py`
- Modify: `packages/grid-agent/tests/analysis/test_workspace.py`
- Create: `scripts/update_trajectory_schemas.py`
- Create: `schemas/grid-run-event-v1.schema.json`
- Create: `docs/architecture/trajectory-events.md`
- Create: `packages/grid-agent/tests/contract/test_trajectory_docs.py`

**Interfaces:**
- Adds `AnalysisWorkspace.events_path`, `requests_path`, `projections_path`, `agent_projection_path`, `business_projection_path`, `context_timeline_path`, and `artifact_index_path`.
- Produces reproducible `RunEvent.model_json_schema()` output.
- Preserves all existing workspace field names and paths.

- [ ] **Step 1: Write failing workspace/schema contract tests**

```python
def test_analysis_workspace_exposes_native_trajectory_paths(tmp_path: Path) -> None:
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-test")
    assert workspace.events_path == workspace.root_path / "events/run-events.jsonl"
    assert workspace.requests_path == workspace.root_path / "requests"
    assert workspace.agent_projection_path == workspace.root_path / "projections/agent-trajectory.json"
    assert workspace.business_projection_path == workspace.root_path / "projections/business-trajectory.json"
    assert workspace.context_timeline_path == workspace.root_path / "projections/context-timeline.json"
    assert workspace.artifact_index_path == workspace.root_path / "projections/artifact-index.json"
    assert workspace.requests_path.is_dir()
    assert workspace.projections_path.is_dir()


def test_checked_in_trajectory_schema_matches_model() -> None:
    root = Path(__file__).resolve().parents[4]
    actual = json.loads((root / "schemas/grid-run-event-v1.schema.json").read_text(encoding="utf-8"))
    assert actual == RunEvent.model_json_schema()


def test_trajectory_docs_publish_fail_closed_contract() -> None:
    root = Path(__file__).resolve().parents[4]
    text = (root / "docs/architecture/trajectory-events.md").read_text(encoding="utf-8")
    for phrase in ("grid-run-event/1.0", "run-events.jsonl", "unknown required event", "last valid sequence"):
        assert phrase in text
```

- [ ] **Step 2: Run and confirm failures**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_workspace.py packages/grid-agent/tests/contract/test_trajectory_docs.py -q`

Expected: FAIL because the new paths, schema, and document do not exist.

- [ ] **Step 3: Add workspace fields and deterministic schema generator**

```python
# scripts/update_trajectory_schemas.py
from __future__ import annotations

import json
from pathlib import Path

from grid_agent.trajectory.events import RunEvent


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "schemas/grid-run-event-v1.schema.json"
    path.write_text(
        json.dumps(RunEvent.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
```

Add the seven workspace fields to the frozen dataclass, create `events/`, `requests/`, and `projections/` in `AnalysisWorkspace.create`, and assign the exact paths from the Interfaces block. Document envelope fields, hash algorithm, allowed source kinds, scope nesting, event vocabulary, recorder terminal failure, artifact-before-event, and fail-closed replay in `trajectory-events.md`.

- [ ] **Step 4: Generate schema and run focused contracts**

Run: `uv run --project packages/grid-agent python scripts/update_trajectory_schemas.py && uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_workspace.py packages/grid-agent/tests/contract/test_trajectory_docs.py -q`

Expected: schema generation changes no file on a second run; all workspace and documentation tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/analysis/workspace.py packages/grid-agent/tests/analysis/test_workspace.py scripts/update_trajectory_schemas.py schemas/grid-run-event-v1.schema.json docs/architecture/trajectory-events.md packages/grid-agent/tests/contract/test_trajectory_docs.py
git commit -m "docs: publish trajectory event protocol"
```

### Task 5: Event-spine integration gate

**Files:**
- Verify only: files introduced in Tasks 1–4.

**Interfaces:**
- Produces verification evidence only; no new source interface.

- [ ] **Step 1: Run the complete trajectory-spine suite**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_events.py packages/grid-agent/tests/trajectory/test_recorder.py packages/grid-agent/tests/trajectory/test_reader.py packages/grid-agent/tests/trajectory/test_artifacts.py packages/grid-agent/tests/contract/test_trajectory_docs.py packages/grid-agent/tests/analysis/test_workspace.py -q`

Expected: all event-spine tests pass with zero skipped tests.

- [ ] **Step 2: Prove schema and canonical output are reproducible**

Run: `uv run --project packages/grid-agent python scripts/update_trajectory_schemas.py && git diff --exit-code -- schemas/grid-run-event-v1.schema.json`

Expected: exit 0 and no schema diff.

- [ ] **Step 3: Run the existing agent regression suite**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests -q`

Expected: the full grid-agent suite passes; no runtime command writes native events yet.

- [ ] **Step 4: Inspect the commit boundary**

Run: `git status --short && git log --oneline -4`

Expected: no uncommitted implementation changes; four task commits are visible. Do not create a verification-only empty commit.

## Self-Review

- Spec coverage: protocol envelope, source kinds, scope, chronology, hash chain, closed payloads, single writer, artifact-before-event, secret/reasoning rejection, fail-closed replay, workspace layout, and schema evolution foundation are covered.
- Deferred intentionally: Pi hooks, request/response contents, decisions/claims, projections, importer, API, UI, and live streaming belong to later plans.
- Type consistency: all later plans consume `EventDraft`, `RunEvent`, `RunEventRecorder`, `RunEventReader`, `ReplayPrefix`, `ArtifactPointer`, and `ImmutableArtifactRegistry` with the signatures declared above.
