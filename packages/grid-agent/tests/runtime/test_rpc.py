from __future__ import annotations

import json
import hashlib
import sys
from collections.abc import Mapping
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from grid_agent.application.workspace import RunWorkspace
from grid_agent.observability.trace import JsonlTraceWriter
from grid_agent.runtime.lock import PiCommand, PiRuntimeIdentity
from grid_agent.runtime.rpc import PiProtocolError, PiRpcClient
from grid_agent.runtime.environment import PiLaunch
from grid_agent.analysis.workspace import AnalysisWorkspace
from grid_agent.trajectory.artifacts import ImmutableArtifactRegistry
from grid_agent.trajectory.capture import CaptureIntegrityError, NativeCaptureAdapter
from grid_agent.trajectory.reader import RunEventReader
from grid_agent.trajectory.recorder import RunEventRecorder


OPEN_RESULT: dict[str, object] = {
    "context_ref": "context:sha256:" + "a" * 64,
    "model": "ieee39",
}


def scripted_rpc_client(tmp_path: Path, *, events: list[dict[str, object]]) -> tuple[PiRpcClient, RunWorkspace]:
    fake = tmp_path / "fake_pi.py"
    fake.write_text(
        "import json\n"
        "json.loads(input())\n"
        f"events={json.dumps(events, ensure_ascii=False)!r}\n"
        "for event in json.loads(events):\n"
        " print(json.dumps(event, ensure_ascii=False), flush=True)\n",
        encoding="utf-8",
    )
    command = PiCommand(
        argv=(sys.executable, str(fake)),
        identity=PiRuntimeIdentity(path=fake, source="explicit_override", package_version="0.80.6", lock_sha256="lock"),
    )
    workspace = RunWorkspace.create(tmp_path / "runs")
    return PiRpcClient(command, workspace, JsonlTraceWriter(workspace.events_path)), workspace


def successful_tool_end(tool_call_id: str, tool_name: str, capability: str, result: Mapping[str, object]) -> dict[str, object]:
    return {
        "type": "tool_execution_end",
        "toolCallId": tool_call_id,
        "toolName": tool_name,
        "isError": False,
        "result": {
            "details": {
                "event": "tool_result",
                "capability": capability,
                "ok": True,
                "result": result,
                "evidence_refs": [],
            }
        },
    }


def semantic_request_fixture(model_id: str = "scripted-model") -> dict[str, Any]:
    return {
        "model": {
            "provider": "scripted",
            "api": "openai-responses",
            "id": model_id,
        },
        "context": {
            "system_prompt": None,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "question"}],
                }
            ],
            "tools": [
                {
                    "name": "grid_context_open",
                    "description": "Open context.",
                    "parameters": {"type": "object", "additionalProperties": False},
                }
            ],
        },
        "options": {},
    }


def model_request_document(
    request_id: str,
    index: int,
    *,
    model_id: str = "scripted-model",
) -> dict[str, Any]:
    semantic = semantic_request_fixture(model_id)
    return {
        "schema_version": "grid-model-request-input/2.0",
        "request_id": request_id,
        "request_index": index,
        "turn_id": "analysis-test-t001",
        "captured_at": "2026-08-14T00:00:00.000Z",
        "source_event_sequences": [7],
        "context_revision": 1,
        "context_state_hash": "a" * 64,
        "runtime": {
            "pi_coding_agent_version": "0.80.6",
            "pi_ai_version": "0.80.6",
            "pi_source_commit": "1" * 40,
            "pi_patch_set_sha256": "2" * 64,
        },
        "semantic_request": semantic,
        "semantic_request_sha256": sha256_canonical_sorted(semantic),
    }


def sha256_canonical_sorted(value: object) -> str:
    encoded = json.dumps(
        sort_json(value),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sort_json(value: object) -> object:
    if isinstance(value, list):
        return [sort_json(item) for item in value]
    if isinstance(value, dict):
        return {key: sort_json(value[key]) for key in sorted(value)}
    return value


def run_prompt_with_timeout(
    client: PiRpcClient,
    capture: NativeCaptureAdapter,
    *,
    timeout: float = 2.0,
) -> dict[str, object]:
    result: dict[str, object] = {}

    def worker() -> None:
        try:
            result["answer"] = client.prompt_and_wait(
                "question",
                capture=capture,
                heartbeat_seconds=1.0,
            )
        except Exception as exc:  # pragma: no cover - asserted by caller
            result["error"] = exc

    thread = Thread(target=worker)
    thread.start()
    thread.join(timeout=timeout)
    if thread.is_alive():
        client.stop()
        thread.join(timeout=1)
        pytest.fail("Pi RPC did not poll model request commits while stdout was blocked")
    return result


def test_rpc_requires_ack_before_agent_end(tmp_path: Path) -> None:
    fake = tmp_path / "fake_pi.py"
    fake.write_text("import json; print(json.dumps({'type':'agent_end'}), flush=True)", encoding="utf-8")
    command = PiCommand(argv=(sys.executable, str(fake)), identity=PiRuntimeIdentity(path=fake, source="explicit_override", package_version="0.80.6", lock_sha256="lock"))
    workspace = RunWorkspace.create(tmp_path / "runs")
    client = PiRpcClient(command, workspace, JsonlTraceWriter(workspace.events_path))
    client.start()
    with pytest.raises(PiProtocolError, match="before prompt acknowledgement"):
        client.prompt_and_wait("question")
    client.stop()


def test_rpc_starts_full_launch_with_its_restricted_environment(tmp_path: Path) -> None:
    fake = tmp_path / "fake_pi.py"
    fake.write_text("import os; assert os.environ['ONLY_ALLOWED'] == 'yes'", encoding="utf-8")
    launch = PiLaunch(argv=(sys.executable, str(fake)), environment={"ONLY_ALLOWED": "yes"})
    workspace = RunWorkspace.create(tmp_path / "runs")
    client = PiRpcClient(launch, workspace, JsonlTraceWriter(workspace.events_path))
    client.start()
    client.stop()


def test_rpc_reports_events_and_idle_heartbeats(tmp_path: Path) -> None:
    fake = tmp_path / "fake_pi.py"
    fake.write_text(
        "import json,time\n"
        "json.loads(input())\n"
        "print(json.dumps({'type':'prompt_ack','ok':True}), flush=True)\n"
        "time.sleep(0.03)\n"
        "print(json.dumps({'type':'text_delta','text':'answer'}), flush=True)\n"
        "print(json.dumps({'type':'agent_end'}), flush=True)\n",
        encoding="utf-8",
    )
    command = PiCommand(
        argv=(sys.executable, str(fake)),
        identity=PiRuntimeIdentity(path=fake, source="explicit_override", package_version="0.80.6", lock_sha256="lock"),
    )
    workspace = RunWorkspace.create(tmp_path / "runs")
    client = PiRpcClient(command, workspace, JsonlTraceWriter(workspace.events_path))
    observed: list[str] = []
    heartbeats: list[None] = []

    client.start()
    try:
        assert client.prompt_and_wait(
            "question",
            on_event=lambda event: observed.append(event["type"]),
            on_heartbeat=lambda: heartbeats.append(None),
            heartbeat_seconds=0.01,
        ) == "answer"
    finally:
        client.stop()

    assert observed == ["prompt_ack", "text_delta", "agent_end"]
    assert heartbeats


def test_rpc_uses_current_pi_prompt_message_protocol(tmp_path: Path) -> None:
    fake = tmp_path / "fake_pi.py"
    fake.write_text(
        "import json\n"
        "request=json.loads(input())\n"
        "if request.get('message') != 'question':\n"
        " print(json.dumps({'type':'response','command':'prompt','success':False,'error':'missing message'}), flush=True)\n"
        "else:\n"
        " print(json.dumps({'type':'response','command':'prompt','success':True}), flush=True)\n"
        " print(json.dumps({'type':'text_delta','text':'answer'}), flush=True)\n"
        " print(json.dumps({'type':'agent_end'}), flush=True)\n",
        encoding="utf-8",
    )
    command = PiCommand(
        argv=(sys.executable, str(fake)),
        identity=PiRuntimeIdentity(path=fake, source="explicit_override", package_version="0.80.6", lock_sha256="lock"),
    )
    workspace = RunWorkspace.create(tmp_path / "runs")
    client = PiRpcClient(command, workspace, JsonlTraceWriter(workspace.events_path))

    client.start()
    try:
        assert client.prompt_and_wait("question") == "answer"
    finally:
        client.stop()


def test_rpc_handles_two_sequential_prompts_in_one_process(tmp_path: Path) -> None:
    fake = tmp_path / "fake_pi.py"
    fake.write_text(
        "import json\n"
        "for index in range(2):\n"
        " request=json.loads(input())\n"
        " print(json.dumps({'type':'response','command':'prompt','success':True,'seen':request['message']}), flush=True)\n"
        " print(json.dumps({'type':'text_delta','text':f'answer-{index + 1}'}), flush=True)\n"
        " print(json.dumps({'type':'agent_end'}), flush=True)\n",
        encoding="utf-8",
    )
    command = PiCommand(
        argv=(sys.executable, str(fake)),
        identity=PiRuntimeIdentity(path=fake, source="explicit_override", package_version="0.80.6", lock_sha256="lock"),
    )
    workspace = RunWorkspace.create(tmp_path / "runs")
    client = PiRpcClient(command, workspace, JsonlTraceWriter(workspace.events_path))
    second: dict[str, object] = {}

    client.start()
    try:
        assert client.prompt_and_wait("first", heartbeat_seconds=0.01) == "answer-1"

        def run_second_prompt() -> None:
            try:
                second["answer"] = client.prompt_and_wait("second", heartbeat_seconds=0.01)
            except Exception as exc:  # pragma: no cover - asserted below for readable failure
                second["error"] = exc

        worker = Thread(target=run_second_prompt)
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive(), "second prompt did not receive its events from the persistent Pi process"
        assert second == {"answer": "answer-2"}
    finally:
        client.stop()


def test_rpc_stops_immediately_on_failed_prompt_response(tmp_path: Path) -> None:
    fake = tmp_path / "fake_pi.py"
    fake.write_text(
        "import json\njson.loads(input())\n"
        "print(json.dumps({'type':'response','command':'prompt','success':False,'error':'preflight failed'}), flush=True)\n",
        encoding="utf-8",
    )
    command = PiCommand(
        argv=(sys.executable, str(fake)),
        identity=PiRuntimeIdentity(path=fake, source="explicit_override", package_version="0.80.6", lock_sha256="lock"),
    )
    workspace = RunWorkspace.create(tmp_path / "runs")
    client = PiRpcClient(command, workspace, JsonlTraceWriter(workspace.events_path))

    client.start()
    try:
        with pytest.raises(PiProtocolError, match="preflight failed"):
            client.prompt_and_wait("question")
    finally:
        client.stop()


def test_rpc_collects_text_from_current_pi_message_updates(tmp_path: Path) -> None:
    fake = tmp_path / "fake_pi.py"
    fake.write_text(
        "import json\njson.loads(input())\n"
        "print(json.dumps({'type':'response','command':'prompt','success':True}), flush=True)\n"
        "print(json.dumps({'type':'message_update','assistantMessageEvent':{'type':'text_delta','delta':'answer'}}), flush=True)\n"
        "print(json.dumps({'type':'agent_end','messages':[]}), flush=True)\n",
        encoding="utf-8",
    )
    command = PiCommand(
        argv=(sys.executable, str(fake)),
        identity=PiRuntimeIdentity(path=fake, source="explicit_override", package_version="0.80.6", lock_sha256="lock"),
    )
    workspace = RunWorkspace.create(tmp_path / "runs")
    client = PiRpcClient(command, workspace, JsonlTraceWriter(workspace.events_path))

    client.start()
    try:
        assert client.prompt_and_wait("question") == "answer"
    finally:
        client.stop()


def test_rpc_emits_semantic_tools_and_omits_streaming_snapshots(tmp_path: Path) -> None:
    client, workspace = scripted_rpc_client(
        tmp_path,
        events=[
            {"type": "response", "command": "prompt", "success": True},
            {"type": "text_delta", "text": "答"},
            {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "案"}},
            {
                "type": "tool_execution_start",
                "toolCallId": "call-1",
                "toolName": "grid_context_open",
                "args": {"model_id": "ieee39"},
            },
            successful_tool_end("call-1", "grid_context_open", "context.open", OPEN_RESULT),
            {"type": "agent_end", "messages": [{"role": "assistant", "content": [{"type": "text", "text": "答案"}]}]},
        ],
    )
    semantic: list[dict[str, object]] = []

    client.start()
    try:
        assert client.prompt_and_wait("question", on_semantic_event=lambda payload, _sequence: semantic.append(payload)) == "答案"
    finally:
        client.stop()

    traced = [json.loads(line)["payload"] for line in workspace.events_path.read_text().splitlines()]
    assert any(item.get("type") == "tool_execution_start" and item["tool_call_id"] == "call-1" for item in semantic)
    assert any(item.get("event") == "tool_result" and item["tool_call_id"] == "call-1" for item in semantic)
    assert {"type": "assistant_message", "text": "答案"} in semantic
    assert {"type": "assistant_message", "text": "答案"} in traced
    assert not any(item.get("type") in {"text_delta", "message_update"} for item in traced)
    assert not any("messages" in item for item in traced)


def test_rpc_persists_canonical_tool_result_from_extension_tool_end_event(tmp_path: Path) -> None:
    evidence_ref = "evidence:sha256:" + "a" * 64
    fake = tmp_path / "fake_pi.py"
    fake.write_text(
        "import json\njson.loads(input())\n"
        "print(json.dumps({'type':'response','command':'prompt','success':True}), flush=True)\n"
        "print(json.dumps({"
        "'type':'tool_execution_start',"
        "'toolName':'grid_topology_branch_endpoints',"
        "'args':{'identifier':'11'}"
        "}), flush=True)\n"
        "print(json.dumps({"
        "'type':'tool_execution_end',"
        "'toolName':'grid_topology_branch_endpoints',"
        "'isError':False,"
        "'result':{'details':{"
        "'event':'tool_result',"
        "'capability':'topology.branch.endpoints.get',"
        "'ok':True,"
        "'result':{'branch':{'identifier':'11'},'evidence_ref':'" + evidence_ref + "'},"
        "'evidence_refs':['" + evidence_ref + "']"
        "}}"
        "}), flush=True)\n"
        "print(json.dumps({'type':'text_delta','text':'answer'}), flush=True)\n"
        "print(json.dumps({'type':'agent_end','messages':[]}), flush=True)\n",
        encoding="utf-8",
    )
    command = PiCommand(
        argv=(sys.executable, str(fake)),
        identity=PiRuntimeIdentity(path=fake, source="explicit_override", package_version="0.80.6", lock_sha256="lock"),
    )
    workspace = RunWorkspace.create(tmp_path / "runs")
    client = PiRpcClient(command, workspace, JsonlTraceWriter(workspace.events_path))

    client.start()
    try:
        assert client.prompt_and_wait("question") == "answer"
    finally:
        client.stop()

    traced_payloads = [
        json.loads(line)["payload"]
        for line in workspace.events_path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        payload.get("event") == "tool_result"
        and payload.get("capability") == "topology.branch.endpoints.get"
        and payload.get("ok") is True
        and payload.get("result") == {"branch": {"identifier": "11"}, "evidence_ref": evidence_ref}
        and payload.get("evidence_refs") == [evidence_ref]
        and payload.get("tool_name") == "grid_topology_branch_endpoints"
        for payload in traced_payloads
    )
    assert any(
        payload.get("type") == "tool_execution_start"
        and payload.get("tool_name") == "grid_topology_branch_endpoints"
        and payload.get("args") == {"identifier": "11"}
        for payload in traced_payloads
    )


def test_rpc_rejects_successful_agent_end_without_answer_text(tmp_path: Path) -> None:
    fake = tmp_path / "fake_pi.py"
    fake.write_text(
        "import json\njson.loads(input())\n"
        "print(json.dumps({'type':'response','command':'prompt','success':True}), flush=True)\n"
        "print(json.dumps({'type':'agent_end','messages':[]}), flush=True)\n",
        encoding="utf-8",
    )
    command = PiCommand(argv=(sys.executable, str(fake)), identity=PiRuntimeIdentity(path=fake, source="explicit_override", package_version="0.80.6", lock_sha256="lock"))
    workspace = RunWorkspace.create(tmp_path / "runs")
    client = PiRpcClient(command, workspace, JsonlTraceWriter(workspace.events_path))
    client.start()
    try:
        with pytest.raises(PiProtocolError, match="without answer text"):
            client.prompt_and_wait("question")
    finally:
        client.stop()


def test_rpc_surfaces_pi_capture_fatal_exit_instead_of_generic_eof(
    tmp_path: Path,
) -> None:
    fake = tmp_path / "fake_pi_capture_fatal.py"
    fake.write_text(
        "import json,sys\n"
        "json.loads(input())\n"
        "print('extension diagnostic before fatal', file=sys.stderr, flush=True)\n"
        "print('trajectory model request commit failed: fsync denied', file=sys.stderr, flush=True)\n"
        "raise SystemExit(86)\n",
        encoding="utf-8",
    )
    command = PiCommand(
        argv=(sys.executable, str(fake)),
        identity=PiRuntimeIdentity(
            path=fake,
            source="explicit_override",
            package_version="0.80.6",
            lock_sha256="lock",
        ),
    )
    workspace = RunWorkspace.create(tmp_path / "runs")
    client = PiRpcClient(command, workspace, JsonlTraceWriter(workspace.events_path))

    client.start()
    try:
        with pytest.raises(
            CaptureIntegrityError,
            match=r"capture-fatal.*86.*trajectory model request commit failed",
        ):
            client.prompt_and_wait("question")
    finally:
        client.stop()


def test_rpc_preserves_capture_fatal_diagnostic_without_legacy_marker(
    tmp_path: Path,
) -> None:
    fake = tmp_path / "fake_pi_capture_detail.py"
    fake.write_text(
        "import json,sys\n"
        "json.loads(input())\n"
        "print('model request capture failed: invalid acknowledgement request_id', file=sys.stderr, flush=True)\n"
        "raise SystemExit(86)\n",
        encoding="utf-8",
    )
    command = PiCommand(
        argv=(sys.executable, str(fake)),
        identity=PiRuntimeIdentity(
            path=fake,
            source="explicit_override",
            package_version="0.80.6",
            lock_sha256="lock",
        ),
    )
    workspace = RunWorkspace.create(tmp_path / "runs")
    client = PiRpcClient(
        command,
        workspace,
        JsonlTraceWriter(workspace.events_path),
    )

    client.start()
    try:
        with pytest.raises(
            CaptureIntegrityError,
            match="invalid acknowledgement request_id",
        ):
            client.prompt_and_wait("question")
    finally:
        client.stop()


def test_rpc_surfaces_provider_error_from_agent_end(tmp_path: Path) -> None:
    fake = tmp_path / "fake_pi.py"
    fake.write_text(
        "import json\njson.loads(input())\n"
        "print(json.dumps({'type':'response','command':'prompt','success':True}), flush=True)\n"
        "print(json.dumps({'type':'agent_end','messages':[{'role':'assistant','content':[],'stopReason':'error','errorMessage':'fetch failed'}]}), flush=True)\n",
        encoding="utf-8",
    )
    command = PiCommand(argv=(sys.executable, str(fake)), identity=PiRuntimeIdentity(path=fake, source="explicit_override", package_version="0.80.6", lock_sha256="lock"))
    workspace = RunWorkspace.create(tmp_path / "runs")
    client = PiRpcClient(command, workspace, JsonlTraceWriter(workspace.events_path))
    client.start()
    try:
        with pytest.raises(PiProtocolError, match="provider failure: fetch failed"):
            client.prompt_and_wait("question")
    finally:
        client.stop()


def test_rpc_waits_for_pi_auto_retry_after_transient_provider_error(tmp_path: Path) -> None:
    client, _workspace = scripted_rpc_client(
        tmp_path,
        events=[
            {"type": "response", "command": "prompt", "success": True},
            {"type": "text_delta", "text": "不完整输出"},
            {
                "type": "agent_end",
                "willRetry": True,
                "messages": [
                    {
                        "role": "assistant",
                        "content": [],
                        "stopReason": "error",
                        "errorMessage": "terminated",
                    }
                ],
            },
            {
                "type": "auto_retry_start",
                "attempt": 1,
                "maxAttempts": 3,
                "delayMs": 0,
                "errorMessage": "terminated",
            },
            {"type": "text_delta", "text": "重试后回答"},
            {
                "type": "agent_end",
                "willRetry": False,
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "重试后回答"}],
                        "stopReason": "stop",
                    }
                ],
            },
            {"type": "auto_retry_end", "success": True, "attempt": 2},
            {"type": "agent_settled"},
        ],
    )

    client.start()
    try:
        assert client.prompt_and_wait("question") == "重试后回答"
    finally:
        client.stop()


def test_rpc_polls_model_request_commits_while_pi_is_blocked(
    tmp_path: Path,
) -> None:
    workspace = AnalysisWorkspace.create(tmp_path / "native", "analysis-test")
    artifacts = ImmutableArtifactRegistry(workspace.root_path)
    recorder = RunEventRecorder(
        workspace.events_path,
        workspace.analysis_id,
        artifact_registry=artifacts,
    )
    capture = NativeCaptureAdapter(recorder, artifacts, workspace)
    capture.begin_turn("analysis-test-t001")
    ack_root = (
        workspace.root_path.parent.parent
        / ".grid-agent"
        / "trajectory-acks"
        / workspace.analysis_id
    )
    provider_count_path = tmp_path / "provider-count.jsonl"
    fake = tmp_path / "fake_blocked_pi.py"
    documents = [
        model_request_document("analysis-test-t001-r001", 1, model_id="first-model"),
        model_request_document("analysis-test-t001-r002", 2, model_id="second-model"),
    ]
    fake.write_text(
        "import json,time\n"
        "from pathlib import Path\n"
        "json.loads(input())\n"
        f"documents=json.loads({json.dumps(documents)!r})\n"
        f"requests_path=Path({str(workspace.requests_path)!r})\n"
        f"acks_path=Path({str(ack_root)!r})\n"
        f"provider_count_path=Path({str(provider_count_path)!r})\n"
        "def emit(payload): print(json.dumps(payload), flush=True)\n"
        "def commit_request(document):\n"
        " path=requests_path/document['request_id']/'input.json'\n"
        " path.parent.mkdir(parents=True, exist_ok=True)\n"
        " path.write_text(json.dumps(document,sort_keys=True,separators=(',',':'))+'\\n',encoding='utf-8')\n"
        " deadline=time.monotonic()+2\n"
        " ack=acks_path/f\"{document['request_id']}.committed.json\"\n"
        " while not ack.is_file():\n"
        "  if time.monotonic()>deadline: raise SystemExit(70)\n"
        "  time.sleep(0.005)\n"
        " with provider_count_path.open('a',encoding='utf-8') as stream: stream.write(document['request_id']+'\\n')\n"
        "commit_request(documents[0])\n"
        "emit({'type':'response','command':'prompt','success':True})\n"
        "commit_request(documents[1])\n"
        "emit({'type':'message_end','message':{'role':'assistant','content':[{'type':'toolCall','id':'call-1','name':'grid_context_open','arguments':{}}],'stopReason':'toolUse'}})\n"
        "emit({'type':'tool_execution_start','toolCallId':'call-1','toolName':'grid_context_open','args':{}})\n"
        "emit({'type':'tool_execution_end','toolCallId':'call-1','toolName':'grid_context_open','isError':False,'result':{'details':{'event':'tool_result','capability':'context.open','ok':True,'result':{},'evidence_refs':[]}}})\n"
        "emit({'type':'response','command':'prompt','success':True})\n"
        "emit({'type':'message_end','message':{'role':'assistant','content':[{'type':'text','text':'answer'}],'stopReason':'stop'}})\n"
        "emit({'type':'text_delta','text':'answer'})\n"
        "emit({'type':'agent_end','messages':[]})\n",
        encoding="utf-8",
    )
    command = PiCommand(
        argv=(sys.executable, str(fake)),
        identity=PiRuntimeIdentity(
            path=fake,
            source="explicit_override",
            package_version="0.80.6",
            lock_sha256="lock",
        ),
    )
    rpc_workspace = RunWorkspace.create(tmp_path / "runs")
    client = PiRpcClient(command, rpc_workspace, JsonlTraceWriter(rpc_workspace.events_path))

    client.start()
    try:
        result = run_prompt_with_timeout(client, capture)
    finally:
        client.stop()

    assert result == {"answer": "answer"}
    provider_invocations = provider_count_path.read_text(encoding="utf-8").splitlines()
    recorded = RunEventReader(recorder.events_path).read_prefix().events
    started = [event for event in recorded if event.event_type == "model.request.started"]
    assert provider_invocations == ["analysis-test-t001-r001", "analysis-test-t001-r002"]
    assert [event.scope.request_id for event in started] == provider_invocations
    assert len({event.payload["artifact_ref"] for event in started}) == 2
    tool_events = [event for event in recorded if event.event_type.startswith("tool.")]
    assert {event.scope.request_id for event in tool_events} == {
        "analysis-test-t001-r001"
    }
    assert [event.event_type for event in recorded] == [
        "model.request.started",
        "model.request.started",
        "model.response.completed",
        "tool.started",
        "tool.completed",
        "model.response.completed",
    ]


def test_rpc_capture_failure_prevents_provider_continuation(tmp_path: Path) -> None:
    workspace = AnalysisWorkspace.create(tmp_path / "native", "analysis-test")
    artifacts = ImmutableArtifactRegistry(workspace.root_path)
    recorder = RunEventRecorder(
        workspace.events_path,
        workspace.analysis_id,
        artifact_registry=artifacts,
    )
    capture = NativeCaptureAdapter(recorder, artifacts, workspace)
    capture.begin_turn("analysis-test-t001")
    provider_count_path = tmp_path / "provider-count.jsonl"
    malformed = model_request_document("analysis-test-t001-r001", 1)
    malformed["runtime"].pop("pi_source_commit")
    fake = tmp_path / "fake_malformed_pi.py"
    fake.write_text(
        "import json,time\n"
        "from pathlib import Path\n"
        "json.loads(input())\n"
        f"document=json.loads({json.dumps(malformed)!r})\n"
        f"requests_path=Path({str(workspace.requests_path)!r})\n"
        f"provider_count_path=Path({str(provider_count_path)!r})\n"
        "path=requests_path/document['request_id']/'input.json'\n"
        "path.parent.mkdir(parents=True, exist_ok=True)\n"
        "path.write_text(json.dumps(document,sort_keys=True,separators=(',',':'))+'\\n',encoding='utf-8')\n"
        "time.sleep(1)\n"
        "with provider_count_path.open('a',encoding='utf-8') as stream: stream.write('entered\\n')\n"
        "print(json.dumps({'type':'text_delta','text':'answer'}), flush=True)\n"
        "print(json.dumps({'type':'agent_end'}), flush=True)\n",
        encoding="utf-8",
    )
    command = PiCommand(
        argv=(sys.executable, str(fake)),
        identity=PiRuntimeIdentity(
            path=fake,
            source="explicit_override",
            package_version="0.80.6",
            lock_sha256="lock",
        ),
    )
    rpc_workspace = RunWorkspace.create(tmp_path / "runs")
    client = PiRpcClient(command, rpc_workspace, JsonlTraceWriter(rpc_workspace.events_path))

    client.start()
    try:
        result = run_prompt_with_timeout(client, capture)
    finally:
        client.stop()

    assert isinstance(result.get("error"), CaptureIntegrityError)
    assert not provider_count_path.exists()
    assert RunEventReader(recorder.events_path).read_prefix().events == ()
