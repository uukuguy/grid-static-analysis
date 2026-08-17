# Grid-Agent Canonical Request Trajectory Implementation Plan

> **Prerequisite:** Complete and verify
> `2026-08-17-pi-canonical-request-hook.md` first.

**Goal:** Restore `make analysis` by recording every final, provider-independent
LLM request through the unified Pi hook, durably and causally before provider
I/O, without grid-agent inspecting provider payload fields.

**Architecture:** The Pi extension consumes only `before_model_request`. It
projects the typed `pi-ai` model/context/options into
`grid-model-request-input/2.0`, atomically writes the immutable input, and blocks
until the Python trajectory recorder acknowledges that it registered the
artifact and appended `model.request.started`. The Python RPC loop polls this
small local commit protocol while awaiting Pi output. Only after the
acknowledgement does the hook return and allow Pi to authenticate, convert the
request, and call the provider. Provider response capture and tool events remain
on their existing normalized paths.

**Design authority:**
`docs/superpowers/specs/2026-08-17-unified-llm-runtime-boundary-design.md`

---

## Task 1: Define the canonical request artifact and typed serializer

**Files**

- Add: `schemas/grid-model-request-input-v2.schema.json`
- Rename: `packages/pi-grid-tools/src/trajectory-capture.mjs` to
  `packages/pi-grid-tools/src/model-request-capture.mjs`
- Rename: `packages/pi-grid-tools/test/trajectory-capture.test.mjs` to
  `packages/pi-grid-tools/test/model-request-capture.test.mjs`
- Modify: `packages/pi-grid-tools/src/domain-tools.mjs`
- Modify: `packages/pi-grid-tools/test/domain-tools.test.mjs`
- Modify: `packages/pi-grid-tools/package.json`

**Step 1: Add failing schema/serializer tests**

Register a `before_model_request` handler with a fixture containing:

- final system prompt;
- user, assistant, and tool-result messages;
- text and tool-call content;
- active tool names, descriptions, and JSON schemas;
- selected provider/API/model identity;
- public inference options;
- runtime version/correlation metadata.

Assert the written file has this exact outer contract:

```json
{
  "schema_version": "grid-model-request-input/2.0",
  "request_id": "analysis-test-t007-r001",
  "request_index": 1,
  "turn_id": "analysis-test-t007",
  "captured_at": "<RFC3339 UTC>",
  "source_event_sequences": [7],
  "context_revision": 3,
  "context_state_hash": "<64 lowercase hex>",
  "runtime": {
    "pi_coding_agent_version": "0.80.6",
    "pi_ai_version": "0.80.6",
    "pi_source_commit": "2b3fda9921b5590f285165287bd442a25817f17b",
    "pi_patch_set_sha256": "<64 lowercase hex>"
  },
  "semantic_request": {
    "model": {
      "provider": "deepseek",
      "api": "openai-completions",
      "id": "deepseek-v4-flash"
    },
    "context": {
      "system_prompt": "...",
      "messages": [],
      "tools": []
    },
    "options": {}
  },
  "semantic_request_sha256": "<sha256 of canonical semantic_request JSON>"
}
```

Use the repository's canonical JSON rule: recursively sorted object keys,
compact UTF-8 JSON, no insignificant whitespace, SHA-256 over only the
`semantic_request` object. The persisted whole document remains one sorted JSON
line plus `\n`.

Also assert the source registers no `before_provider_request` handler.

Run:

```sh
npm test --prefix packages/pi-grid-tools -- \
  test/model-request-capture.test.mjs
```

Expected: FAIL because the existing source consumes `event.payload` and emits
schema `1.0`.

**Step 2: Add the JSON Schema**

Define closed objects (`additionalProperties: false`) for the outer document,
runtime identity, model identity, context, public options, messages, content
blocks, tools, and tool input schemas. Permit arbitrary JSON only where the
stable `pi-ai` contract requires it: tool arguments, tool-result details, and
tool parameter JSON Schema.

The schema must not contain `provider_payload`, credentials, headers, transport
callbacks, or provider-specific field names.

**Step 3: Implement a type-directed canonical projection**

Replace raw recursive provider-payload normalization with explicit functions:

```js
function canonicalModel(model) {
  return { provider: model.provider, api: model.api, id: model.id };
}

function canonicalContext(context) {
  return {
    system_prompt: context.systemPrompt ?? null,
    messages: context.messages.map(canonicalMessage),
    tools: (context.tools ?? []).map(canonicalTool),
  };
}

function canonicalOptions(options) {
  return pickDefined(options, [
    "reasoning", "thinkingBudgets", "temperature", "maxTokens",
    "transport", "cacheRetention", "timeoutMs",
    "websocketConnectTimeoutMs", "maxRetries", "maxRetryDelayMs",
  ]);
}
```

`canonicalMessage()` switches on the documented `pi-ai` roles and content block
types. It copies stable text, image, tool-call, and tool-result data. It applies
the existing trajectory privacy rule to thinking blocks and omits opaque
`textSignature`, `thinkingSignature`, and `thoughtSignature` members through
typed projection, not a recursive provider-key denylist. A redacted thinking
block records only `{ "type": "thinking", "redacted": true }`; it never
persists the thinking text or signature. This preserves the exact public
semantic input and makes private continuation state explicitly unavailable
rather than silently presenting it as replayable.

Reject unknown `pi-ai` roles/content variants with
`CanonicalRequestContractError` before I/O. Do not accept arbitrary object
spreads in model, message, content, tool, or options projection.

**Step 4: Preserve atomic immutable persistence**

Reuse the existing exclusive-directory, temporary-file, file-fsync, atomic
rename, and directory-fsync implementation. Remove:

- `CREDENTIAL_KEY_PATTERN`;
- `HIDDEN_REASONING_KEYS`;
- `normalizeJsonPayload()`;
- `normalizeKey()`;
- all access to `event.payload`.

The only generic JSON validator remains at explicitly arbitrary JSON leaves and
rejects non-finite numbers, cycles, sparse arrays, functions, symbols, BigInt,
and non-plain objects.

**Step 5: Run focused tests**

Cover deterministic digest, repeat requests, immutable paths, invalid turn and
capture state, write/fsync failure, unknown semantic variants, private
signature redaction, and two different provider identities producing the same
context shape.

```sh
npm run check --prefix packages/pi-grid-tools
npm test --prefix packages/pi-grid-tools -- \
  test/model-request-capture.test.mjs test/domain-tools.test.mjs
```

Expected: PASS.

**Step 6: Commit the artifact slice**

```sh
git add schemas/grid-model-request-input-v2.schema.json \
  packages/pi-grid-tools/src/model-request-capture.mjs \
  packages/pi-grid-tools/src/domain-tools.mjs \
  packages/pi-grid-tools/test/model-request-capture.test.mjs \
  packages/pi-grid-tools/test/domain-tools.test.mjs \
  packages/pi-grid-tools/package.json
git add -u packages/pi-grid-tools/src/trajectory-capture.mjs \
  packages/pi-grid-tools/test/trajectory-capture.test.mjs
git commit -m "feat: capture canonical model requests"
```

---

## Task 2: Add the pre-I/O commit acknowledgement protocol

**Files**

- Modify: `packages/pi-grid-tools/src/model-request-capture.mjs`
- Modify: `packages/pi-grid-tools/test/model-request-capture.test.mjs`
- Modify: `packages/grid-agent/src/grid_agent/runtime/environment.py`
- Modify: `packages/grid-agent/tests/runtime/test_pi_config.py`
- Modify: `packages/grid-agent/src/grid_agent/application/paths.py`
- Modify: `packages/grid-agent/tests/application/test_paths.py`

**Step 1: Write a failing blocking-order test**

Invoke the hook without creating an acknowledgement. Assert the returned
promise remains pending and a fake provider continuation has not run. Then
write a matching acknowledgement atomically and assert the hook resolves.

Add negative cases for wrong request ID, digest mismatch, failed status, unsafe
path, and timeout. Assert all reject before the continuation runs.

**Step 2: Define an internal acknowledgement location**

Add an ignored internal directory under `.grid-agent/trajectory-acks/<analysis
id>/`, not under `runs/`. Pass its explicit absolute path as
`GRID_AGENT_TRAJECTORY_ACKS`. Keep permissions owner-only. It is transport state,
not evidence, and may be cleaned only for the current analysis during normal
workspace creation; never delete another run's state or any existing `var/`
data.

Add public runtime identity environment values from the verified
`PiRuntimeIdentity`:

```text
GRID_AGENT_PI_CODING_AGENT_VERSION
GRID_AGENT_PI_AI_VERSION
GRID_AGENT_PI_SOURCE_COMMIT
GRID_AGENT_PI_PATCH_SET_SHA256
```

Remove `GRID_AGENT_PROVIDER_ID` and `GRID_AGENT_MODEL_ID` from native capture;
the selected identity now comes from the typed hook event. Continue passing
provider credentials only through their existing provider env variables.

**Step 3: Wait for a correlated durable acknowledgement**

After `input.json` is fsynced, wait for
`<acks>/<request_id>.committed.json`. Validate:

```json
{
  "schema_version": "grid-model-request-commit/1.0",
  "request_id": "analysis-test-t007-r001",
  "semantic_request_sha256": "<same digest>",
  "artifact_ref": "artifact:sha256:<registry digest>",
  "event_sequence": 12,
  "status": "committed"
}
```

Use bounded polling with a 25 ms interval and a 30-second monotonic deadline.
Read only the exact derived filename after validating `request_id`. The hook
returns only after a valid `committed` acknowledgement. A timeout or malformed
acknowledgement calls the existing fatal path with exit 86 because it is a
genuine pre-call durability failure, not provider schema validation.

**Step 4: Run focused JS and environment tests**

```sh
npm test --prefix packages/pi-grid-tools -- \
  test/model-request-capture.test.mjs
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/runtime/test_pi_config.py \
  packages/grid-agent/tests/application/test_paths.py -q
```

Expected: PASS.

**Step 5: Commit the commit-protocol client**

```sh
git add packages/pi-grid-tools/src/model-request-capture.mjs \
  packages/pi-grid-tools/test/model-request-capture.test.mjs \
  packages/grid-agent/src/grid_agent/runtime/environment.py \
  packages/grid-agent/tests/runtime/test_pi_config.py \
  packages/grid-agent/src/grid_agent/application/paths.py \
  packages/grid-agent/tests/application/test_paths.py
git commit -m "feat: block model IO on trajectory commit"
```

---

## Task 3: Commit request artifacts and events from the Python recorder

**Files**

- Modify: `packages/grid-agent/src/grid_agent/trajectory/capture.py`
- Modify: `packages/grid-agent/src/grid_agent/runtime/rpc.py`
- Modify: `packages/grid-agent/tests/trajectory/test_capture.py`
- Modify: `packages/grid-agent/tests/runtime/test_rpc.py`

**Step 1: Replace provider-document tests with canonical-document tests**

Rename test helpers and assertions from `provider request` to `model request`.
Construct schema `2.0` documents and verify:

- `semantic_request_sha256` is recomputed, not trusted;
- provider/model in `_RequestState` come from
  `semantic_request.model.provider/id`;
- runtime/model/context/options required shapes are validated;
- request indexes remain monotonic and paths match request IDs;
- duplicate files are idempotent;
- malformed documents never receive an acknowledgement;
- a valid artifact is registered and `model.request.started` is appended before
  the acknowledgement becomes visible.

Run and confirm the old loader fails on schema `2.0`.

**Step 2: Rename and harden the ingestion method**

Rename `drain_provider_requests()` to `drain_model_requests()`. Split parsing
into a `CanonicalModelRequestDocument` value object or equivalent typed helper;
do not scatter raw mapping access across the adapter.

Validation order:

1. parse one JSON object;
2. validate schema/version/correlations/runtime shape;
3. canonicalize and recompute semantic digest;
4. register the immutable existing artifact;
5. append `model.request.started` with causal source sequence;
6. atomically write and fsync the acknowledgement containing artifact ref and
   event sequence;
7. update in-memory request state.

If steps 1–6 fail, do not advance `_last_request_index` or `_seen_requests`.
An acknowledgement file is exclusive and immutable; a conflicting existing ack
is an integrity error.

**Step 3: Poll commits while Pi is blocked**

In `PiRpcClient.prompt_and_wait()`, call `capture.drain_model_requests()`:

- immediately after sending the prompt;
- on each queue timeout while awaiting stdout;
- before handling each decoded RPC event;
- once before returning or raising on terminal Pi events.

When capture is active, cap the queue wait at 25 ms so Pi does not incur a
heartbeat-length delay per request. Preserve the configured heartbeat deadline
and callback behavior; the short poll is internal and must not emit fake
heartbeats.

Keep exit code 86 mapping, but change its message to
`trajectory model request commit failed`. Remove any mention of payload
normalization or prohibited provider keys.

**Step 4: Prove the causal order**

Use a fake child process and synchronization events:

```text
Pi hook writes input -> Python registers artifact -> Python appends event
-> Python writes ack -> Pi provider fixture enters
```

Assert there is exactly one request artifact and one request-started event per
provider invocation, including a multi-round tool call. Assert capture failure
prevents the provider fixture count from increasing.

**Step 5: Run focused Python tests**

```sh
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/trajectory/test_capture.py \
  packages/grid-agent/tests/runtime/test_rpc.py -q
```

Expected: PASS.

**Step 6: Commit the recorder slice**

```sh
git add packages/grid-agent/src/grid_agent/trajectory/capture.py \
  packages/grid-agent/src/grid_agent/runtime/rpc.py \
  packages/grid-agent/tests/trajectory/test_capture.py \
  packages/grid-agent/tests/runtime/test_rpc.py
git commit -m "feat: commit model request events before provider IO"
```

---

## Task 4: Migrate scripted runs, replay, API, and documentation

**Files**

- Modify: `packages/grid-agent/tests/e2e/test_semantic_pi_path.py`
- Modify: `packages/grid-agent/tests/e2e/test_continuous_analysis.py`
- Modify: `packages/grid-agent/tests/trajectory/api/test_app.py`
- Modify: `packages/grid-agent/tests/trajectory/api/test_projection_pages.py`
- Modify: `packages/grid-agent/tests/trajectory/projections/test_context.py`
- Modify: `packages/grid-agent/src/grid_agent/trajectory/service.py`
- Modify: `docs/architecture/trajectory-events.md`
- Modify: `docs/architecture/analysis-context.md`
- Modify: `docs/TRAJECTORY-WORKBENCH-OPERATOR-GUIDE.md`
- Modify: `docs/MANUAL-VALIDATION.md`

**Step 1: Update scripted producers**

Make every scripted current-run fixture write a valid schema `2.0` semantic
request and participate in the commit acknowledgement protocol. Do not retain a
schema `1.0` producer for new runs.

Assertions must verify final system prompt, messages, tool schemas, public
options, runtime identity, digest, and absence of credentials/private thinking.

**Step 2: Preserve historical runs without mutation**

The read-only trajectory service continues indexing immutable
`requests/*/input.json` artifacts regardless of v1/v2. The native current-run
capture accepts only v2. Legacy/import readers may label v1 request artifacts
as historical raw-provider input, but must not rewrite them, infer missing v2
fields, or make them drive current-run context replay.

Add fixtures proving a v1 historical run remains byte-for-byte unchanged and
readable after catalog/API access.

**Step 3: Keep public projections normalized**

Business, Agent, Context, Evidence, and Execution continue consuming
`model.request.started` and verified artifact refs. They must not depend on the
v2 internal JSON layout unless displaying the Context request preview.

For that preview, expose only `semantic_request` plus correlations and runtime
identity. Never expose internal acknowledgements. Preserve the existing direct
artifact integrity endpoint and its content hash behavior.

Add response-body assertions:

```py
assert "provider_payload" not in response.text
assert "reasoning_content" not in response.text
assert "thinkingSignature" not in response.text
assert "GRID_AGENT_TRAJECTORY_ACKS" not in response.text
```

**Step 4: Update operator and architecture docs**

Document that:

- the center Context request link is final provider-independent semantic input;
- request commit precedes provider I/O;
- provider wire payloads are deliberately unavailable;
- private reasoning/signatures are deliberately redacted;
- historical v1 artifacts are readable but not equivalent to v2 canonical
  replay;
- a failed pre-call commit is an analysis integrity failure, not a provider
  failure.

Remove documentation that calls `provider_payload` the current exact replay
source.

**Step 5: Run replay/API/E2E tests**

```sh
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/trajectory \
  packages/grid-agent/tests/e2e/test_semantic_pi_path.py \
  packages/grid-agent/tests/e2e/test_continuous_analysis.py -q
```

Expected: PASS.

**Step 6: Commit the migration slice**

```sh
git add packages/grid-agent/tests/e2e \
  packages/grid-agent/tests/trajectory \
  packages/grid-agent/src/grid_agent/trajectory/service.py \
  docs/architecture/trajectory-events.md \
  docs/architecture/analysis-context.md \
  docs/TRAJECTORY-WORKBENCH-OPERATOR-GUIDE.md \
  docs/MANUAL-VALIDATION.md
git commit -m "docs: migrate trajectory to canonical request replay"
```

---

## Task 5: Remove the obsolete provider capture path

**Files**

- Search/modify: `packages/grid-agent/**`
- Search/modify: `packages/pi-grid-tools/**`
- Search/modify: `schemas/**`
- Search/modify: `docs/architecture/**`
- Preserve as historical records: superseded files under
  `docs/superpowers/specs/` and `docs/superpowers/plans/`

**Step 1: Add a source-boundary regression test**

Add a focused test or static assertion over current production source (excluding
historical docs and legacy fixtures) that rejects:

```text
before_provider_request
provider_payload
HIDDEN_REASONING_KEYS
CREDENTIAL_KEY_PATTERN
drain_provider_requests
```

This is an architectural guard, not a provider-field allow/deny list.

**Step 2: Remove obsolete names and environment values**

Delete all current registration, parser, error-message, and env configuration
for the raw provider request path. Keep `before_provider_request` available
inside Pi itself for other consumers; grid-agent simply does not subscribe to
it.

Do not delete historical plan/spec text or mutate old run directories.

**Step 3: Run focused grep and all offline gates**

```sh
rg -n "before_provider_request|provider_payload|drain_provider_requests" \
  packages/grid-agent/src packages/pi-grid-tools/src schemas
make doctor
make test
make test-e2e
make validate
```

Expected: `rg` has no production hits; every non-billable gate passes; CLI
stdout remains exactly one JSON object with only `question_id` and
`answer_output`.

**Step 4: Commit cleanup**

```sh
git add packages/grid-agent packages/pi-grid-tools schemas
git commit -m "refactor: remove provider payload trajectory capture"
```

---

## Task 6: Verify the real core entry point

**Files**

- Inspect only: `runs/<new-analysis-id>/`
- Update after verification: `docs/MANUAL-VALIDATION.md`

**Step 1: Confirm authorization and credentials**

This step is billable. Run it only when the user explicitly authorizes live
provider use and the configured DeepSeek credentials are present. Offline gates
do not substitute for this acceptance test.

**Step 2: Reinstall the patched managed runtime**

```sh
make install-pi
make doctor
```

Expected: doctor identifies the verified patched runtime and reports readiness.

**Step 3: Run the exact reported entry point**

```sh
make analysis
```

Expected:

- exit code `0`;
- exactly one stdout JSON envelope;
- `status=completed` in diagnostics/report;
- multiple tool rounds may occur normally;
- no failure involving `reasoning_content`, provider payload keys, or missing
  request replay;
- every model request has a v2 canonical artifact and a preceding durable
  `model.request.started` commit acknowledgement.

**Step 4: Inspect the new run without modifying it**

Verify artifact/event counts and hashes, then open it in the trajectory
workbench. Confirm Business, Agent, Context, Evidence, and Execution load and
the Context request preview shows final semantic input without private provider
fields.

**Step 5: Record the manual result**

Add the run ID, provider/model identifiers, timestamp, commands, and pass/fail
observations to `docs/MANUAL-VALIDATION.md`. Do not commit credentials, provider
payloads, hidden reasoning, or generated `runs/` contents.

```sh
git add docs/MANUAL-VALIDATION.md
git commit -m "test: verify canonical DeepSeek analysis path"
```

---

## Plan verification checklist

Before claiming the bug fixed:

- New runs use only `grid-model-request-input/2.0`.
- Each provider invocation has exactly one committed request artifact and one
  `model.request.started` event before provider I/O.
- The request digest is independently recomputed by Python.
- Capture failure prevents authentication/network invocation.
- No current grid-agent/trajectory source reads provider payloads or branches on
  provider-private keys.
- Runtime identity includes pinned Pi, `pi-ai`, source commit, and patch digest.
- Private reasoning/signatures, credentials, headers, callbacks, and arbitrary
  metadata are absent from artifacts and APIs.
- v1 historical runs remain immutable and readable.
- Tool capability and `gridctl` protocol boundaries are unchanged.
- `make doctor`, `make test`, `make test-e2e`, and `make validate` pass.
- The explicitly authorized live `make analysis` run completes successfully.

