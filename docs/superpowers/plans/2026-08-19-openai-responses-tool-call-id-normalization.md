# OpenAI Responses Tool Call ID Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize provider-defined Pi tool call IDs before native capture so OpenAI Responses compound IDs cannot invalidate trajectory artifacts.

**Architecture:** Keep raw Pi RPC/session events unchanged. At the RPC-to-semantic boundary, retain artifact-safe IDs verbatim and map every other non-empty ID deterministically to `pi-call-<sha256>`; both start and result events pass through the same function.

**Tech Stack:** Python 3.11+, standard-library `hashlib` and `re`, pytest.

## Global Constraints

- Do not change Pi provider-facing IDs or Responses replay.
- Do not broaden the artifact identity filename alphabet.
- Preserve safe existing IDs unchanged.
- Preserve raw IDs in `runs/<run-id>/pi/*.jsonl`.

---

### Task 1: Normalize unsafe tool call IDs at the semantic RPC boundary

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/runtime/rpc.py`
- Test: `packages/grid-agent/tests/runtime/test_rpc.py`

**Interfaces:**
- Consumes: raw non-empty Pi `toolCallId` or `tool_call_id` strings.
- Produces: `_semantic_tool_call_id(value: str) -> str`, returning either the unchanged safe ID or `pi-call-<64 hex characters>`.

- [x] **Step 1: Write the failing regression tests**

Change the native-capture RPC fixture to use `call_provider|fc_item` for both
tool start and end. Assert that capture completes, both semantic events share
the expected SHA-256-derived ID, and the immutable artifact filename uses that
safe ID. Retain the existing `call-1` test as proof that safe IDs are unchanged.

- [x] **Step 2: Run the focused regression test and verify RED**

```sh
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/runtime/test_rpc.py::test_rpc_polls_model_request_commits_while_pi_is_blocked -q
```

Expected: fail with `ArtifactIntegrityError: artifact identity is invalid`.

- [x] **Step 3: Implement the minimal normalization**

Add an RPC-local safe identity regex matching the artifact registry contract.
Have `_event_tool_call_id()` read the raw string, preserve a safe match, and
otherwise return `pi-call-` plus the full SHA-256 digest of the raw UTF-8 value.

- [x] **Step 4: Verify focused and complete tests GREEN**

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_rpc.py -q
make test-agent
```

Expected: all RPC tests and all grid-agent tests pass.

- [x] **Step 5: Verify the actual local Responses tool path**

```sh
make run-llm QUESTION='IEEE-39节点系统中线路11连接哪两个母线?'
```

Expected: `grid_model_list` completes and the run proceeds through subsequent
tools without `ArtifactIntegrityError`.

- [x] **Step 6: Commit the isolated fix**

```sh
git add packages/grid-agent/src/grid_agent/runtime/rpc.py \
  packages/grid-agent/tests/runtime/test_rpc.py \
  docs/superpowers/plans/2026-08-19-openai-responses-tool-call-id-normalization.md
git commit -m "fix: normalize Pi tool call identities"
```
