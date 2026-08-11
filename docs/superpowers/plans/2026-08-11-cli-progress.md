# CLI Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show live, redacted Pi/LLM progress on stderr without changing the final stdout JSON contract.

**Architecture:** `PiRpcClient` accepts event and heartbeat callbacks while waiting for JSONL. The CLI formats these callbacks as timestamped progress lines and truncates visible input/output to 200 characters.

**Tech Stack:** Python 3.12, Typer, subprocess JSONL RPC, pytest.

## Global Constraints

- stdout remains exactly one `AnswerEnvelope` JSON object.
- Progress and diagnostics go only to stderr.
- Never print credentials; visible text is limited to 200 characters.

---

### Task 1: RPC callbacks

**Files:**
- Modify: `packages/grid-agent/tests/runtime/test_rpc.py`
- Modify: `packages/grid-agent/src/grid_agent/runtime/rpc.py`

- [ ] Write a failing test proving a prompt acknowledgement and text event reach an observer, and an idle read invokes a heartbeat.
- [ ] Implement optional `on_event` and `on_heartbeat` callbacks in `prompt_and_wait` using a queue-backed stdout reader.
- [ ] Run `pytest packages/grid-agent/tests/runtime/test_rpc.py -q`.

### Task 2: CLI reporter

**Files:**
- Modify: `packages/grid-agent/tests/e2e/test_offline_walking_skeleton.py`
- Modify: `packages/grid-agent/src/grid_agent/cli/app.py`

- [ ] Write a failing E2E assertion for stderr progress while stdout remains an envelope.
- [ ] Add a 200-character stderr reporter and connect it to `PiRpcClient`.
- [ ] Run the E2E test and all agent tests.
