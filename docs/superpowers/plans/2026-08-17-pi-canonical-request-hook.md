# Pi Canonical Model Request Hook Implementation Plan

> **Dependency:** Execute this plan before
> `2026-08-17-grid-agent-canonical-request-trajectory.md`.

**Goal:** Add one provider-neutral, blocking pre-invocation hook to the pinned Pi
runtime so applications can observe the exact final `pi-ai` model invocation
without receiving provider wire payloads.

**Architecture:** Maintain the change as an upstream-ready patch against the
exact Pi commit pinned by `configs/runtime/pi-runtime.lock.json`. The managed Pi
installer verifies the patch digest, applies it after checkout, and builds the
patched source. The hook runs in `createAgentSession()` after the agent loop has
completed context transformation and `convertToLlm`, but before authentication,
provider conversion, or network I/O. Its event exposes a read-only snapshot of
the selected `Model`, final `Context`, and an explicit allowlist of public
`SimpleStreamOptions`; it never exposes API keys, environment variables,
headers, callbacks, signals, metadata, or provider payloads.

**Design authority:**
`docs/superpowers/specs/2026-08-17-unified-llm-runtime-boundary-design.md`

**Pinned upstream baseline:** `earendil-works/pi` commit
`2b3fda9921b5590f285165287bd442a25817f17b`, package version `0.80.6`.

---

## Task 1: Define the provider-neutral Pi extension contract

**Files**

- Add: `configs/runtime/patches/pi-0.80.6-before-model-request.patch`
- Upstream file represented in patch:
  `packages/coding-agent/src/core/extensions/types.ts`
- Upstream file represented in patch:
  `packages/coding-agent/src/core/extensions/index.ts`
- Upstream file represented in patch: `packages/coding-agent/src/index.ts`
- Upstream test represented in patch:
  `packages/coding-agent/test/sdk-before-model-request.test.ts`

**Step 1: Write a failing upstream type/runtime test**

Create a fixture extension through `createAgentSession()` that registers
`pi.on("before_model_request", handler)`. The handler records the event and the
mock provider records when its `streamSimple` implementation is entered.

The first test must assert this order and shape:

```ts
expect(order).toEqual(["before_model_request", "provider"]);
expect(observed).toMatchObject({
  type: "before_model_request",
  model: {
    provider: "capture-provider",
    api: "openai-completions",
    id: "capture-model",
  },
  context: {
    systemPrompt: "final system prompt",
    messages: [{ role: "user", content: [{ type: "text", text: "question" }] }],
    tools: [{ name: "grid_model_list" }],
  },
  options: {
    reasoning: "medium",
    temperature: 0.2,
    maxTokens: 1024,
    transport: "sse",
    cacheRetention: "short",
    timeoutMs: 1234,
    websocketConnectTimeoutMs: 2345,
    maxRetries: 2,
    maxRetryDelayMs: 3000,
  },
});
```

Also assert that `apiKey`, `env`, `headers`, `signal`, `onPayload`,
`onResponse`, `metadata`, and `sessionId` are absent from `event.options`.
`sessionId` is correlation/transport state, not semantic replay input.

Run against a clean checkout of the pinned Pi commit:

```sh
npm test --workspace @earendil-works/pi-coding-agent -- \
  sdk-before-model-request.test.ts
```

Expected: FAIL because `before_model_request` is not an `ExtensionAPI` event.

**Step 2: Add the typed event**

Add this public contract to `extensions/types.ts`:

```ts
export interface PublicModelRequestOptions {
  reasoning?: ThinkingLevel;
  thinkingBudgets?: Readonly<ThinkingBudgets>;
  temperature?: number;
  maxTokens?: number;
  transport?: Transport;
  cacheRetention?: CacheRetention;
  timeoutMs?: number;
  websocketConnectTimeoutMs?: number;
  maxRetries?: number;
  maxRetryDelayMs?: number;
}

export interface BeforeModelRequestEvent {
  type: "before_model_request";
  model: Readonly<Model<Api>>;
  context: Readonly<Context>;
  options: Readonly<PublicModelRequestOptions>;
}
```

Import `CacheRetention`, `ThinkingBudgets`, and `Transport` from `pi-ai`.
Include `BeforeModelRequestEvent` in `ExtensionEvent`, add the overload to
`ExtensionAPI.on`, and re-export the two new types through
`core/extensions/index.ts` and the coding-agent package root.

The event is observation-only: it has no result type and cannot replace model,
context, or options.

**Step 3: Add a fail-closed runner method**

Add `emitBeforeModelRequest()` to `ExtensionRunner`. Unlike display-oriented
extension events, this method must propagate handler failures to the caller so a
durability observer can prevent an unrecorded billable request:

```ts
async emitBeforeModelRequest(
  model: Model<Api>,
  context: Context,
  options: PublicModelRequestOptions,
): Promise<void> {
  const ctx = this.createContext();
  for (const ext of this.extensions) {
    for (const handler of ext.handlers.get("before_model_request") ?? []) {
      const event: BeforeModelRequestEvent = {
        type: "before_model_request",
        model: structuredClone(model),
        context: structuredClone(context),
        options: structuredClone(options),
      };
      await handler(event, ctx);
    }
  }
}
```

Do not route this method through the existing catch-and-log behavior used by
`emitBeforeProviderRequest`; swallowing a persistence error would break the
pre-call guarantee.

**Step 4: Prove handler failure blocks the provider**

Add a second test whose handler throws `new Error("commit failed")`. Assert the
`session.agent.streamFn(...)` promise rejects with that error and the mock
provider call count remains zero.

Run:

```sh
npm test --workspace @earendil-works/pi-coding-agent -- \
  sdk-before-model-request.test.ts
```

Expected: the type surface compiles, but the behavior tests still FAIL until the
SDK stream boundary emits the event.

**Step 5: Commit the contract slice**

Generate the patch from the clean pinned checkout and add it to this repository.
Do not edit files under an installed `.grid-agent/runtime/pi/source` tree.

```sh
git add configs/runtime/patches/pi-0.80.6-before-model-request.patch
git commit -m "feat: define canonical Pi request hook"
```

---

## Task 2: Emit the hook at the exact invocation boundary

**Files**

- Modify: `configs/runtime/patches/pi-0.80.6-before-model-request.patch`
- Upstream file represented in patch: `packages/coding-agent/src/core/sdk.ts`
- Upstream file represented in patch:
  `packages/coding-agent/test/sdk-before-model-request.test.ts`

**Step 1: Add exact-context and immutability assertions**

Extend the test so the passed `Context` contains the final converted messages,
final system prompt, and currently active tool schemas. Have the observer mutate
its received snapshot and assert the mock provider still receives the original
context. This proves both placement and observation-only behavior.

Add a provider matrix with two fixture APIs, for example
`openai-completions` and `anthropic-messages`, and assert the observed canonical
shape is identical apart from `model.api`. No raw provider payload is available
to the observer.

Run the focused test and confirm failure.

**Step 2: Normalize only public options**

Add a local helper in `sdk.ts`:

```ts
function publicModelRequestOptions(
  options: SimpleStreamOptions | undefined,
  resolved: {
    timeoutMs: number;
    websocketConnectTimeoutMs: number;
    maxRetries: number;
    maxRetryDelayMs: number;
  },
): PublicModelRequestOptions {
  return omitUndefined({
    reasoning: options?.reasoning,
    thinkingBudgets: options?.thinkingBudgets,
    temperature: options?.temperature,
    maxTokens: options?.maxTokens,
    transport: options?.transport,
    cacheRetention: options?.cacheRetention,
    timeoutMs: resolved.timeoutMs,
    websocketConnectTimeoutMs: resolved.websocketConnectTimeoutMs,
    maxRetries: resolved.maxRetries,
    maxRetryDelayMs: resolved.maxRetryDelayMs,
  });
}
```

The helper is field-by-field. Never spread `options`, because future provider
fields must not silently enter the public contract.

**Step 3: Emit before auth and provider work**

Refactor `createAgentSession()`'s `streamFn` to resolve settings-only defaults,
then await the new runner method before `modelRegistry.getApiKeyAndHeaders()`:

```ts
const retry = settingsManager.getProviderRetrySettings();
const resolved = resolvePublicRequestOptions(options, retry, settingsManager);
const runner = extensionRunnerRef.current;
if (runner?.hasHandlers("before_model_request")) {
  await runner.emitBeforeModelRequest(
    model,
    context,
    publicModelRequestOptions(options, resolved),
  );
}

const auth = await modelRegistry.getApiKeyAndHeaders(model);
// Existing auth/header/provider invocation follows unchanged.
return streamSimple(model, context, providerOptions);
```

Resolve timeouts/retry defaults only once and reuse those exact values in the
later `streamSimple` call. Do not call auth before the hook; OAuth refresh may
perform network I/O.

**Step 4: Run pinned Pi verification**

Apply the patch to a clean checkout of the pinned commit and run:

```sh
npm test --workspace @earendil-works/pi-coding-agent -- \
  sdk-before-model-request.test.ts sdk-stream-options.test.ts
npm run build
git diff --check
```

Expected: all tests pass, the monorepo builds, and the patch applies with no
fuzz or uncommitted generated files.

**Step 5: Commit the behavior slice**

```sh
git add configs/runtime/patches/pi-0.80.6-before-model-request.patch
git commit -m "feat: emit canonical request before provider IO"
```

---

## Task 3: Make the managed runtime patch reproducible and tamper-evident

**Files**

- Modify: `configs/runtime/pi-runtime.lock.json`
- Modify: `packages/grid-agent/src/grid_agent/runtime/lock.py`
- Modify: `packages/grid-agent/src/grid_agent/runtime/installer.py`
- Modify: `packages/grid-agent/tests/runtime/test_installer.py`
- Modify: `packages/grid-agent/tests/runtime/test_locator.py`

**Step 1: Write failing lock and installer tests**

Update fixtures to expect lock schema version `2`, the exact `pi-ai` version,
and a required patch entry:

```json
"pi_ai_version": "0.80.6",
"patches": [
  {
    "path": "patches/pi-0.80.6-before-model-request.patch",
    "sha256": "the lowercase SHA-256 computed from the committed patch bytes"
  }
]
```

Add tests that assert:

- an absent patch, wrong digest, absolute path, or `..` path is rejected;
- installer verifies bytes before invoking Git;
- installer runs `git apply --check <absolute-patch-path>` then
  `git apply <absolute-patch-path>` after detached checkout and before `npm ci`;
- failed verification/application never writes the `active` marker;
- marker and `PiRuntimeIdentity` include a deterministic combined patch digest.

Run:

```sh
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/runtime/test_installer.py \
  packages/grid-agent/tests/runtime/test_locator.py -q
```

Expected: FAIL because schema v1 has no patch contract.

**Step 2: Implement lock parsing and validation**

Add an immutable patch identity:

```py
@dataclass(frozen=True)
class PiRuntimePatch:
    path: Path
    sha256: str
```

`PiRuntimeLock.load()` resolves patch paths relative to
`configs/runtime/pi-runtime.lock.json`, rejects paths escaping that directory,
verifies `^[0-9a-f]{64}$`, verifies file bytes immediately, and stores
`patches: tuple[PiRuntimePatch, ...]`. The lock file hash continues to cover the
patch declarations; the explicit file digests cover patch contents. Add
`pi_ai_version` and `patches_sha256` to `PiRuntimeIdentity` so downstream
capture records the actual managed runtime, not a duplicated environment
constant.

**Step 3: Apply patches before dependency installation**

After detached checkout, apply each verified patch in declared order with
argument arrays and `shell=False`. Re-read and re-hash each file immediately
before `git apply --check` to close the load/apply time gap.

Write the active marker only after patching, `npm ci`, build, executable check,
and version probe all succeed:

```text
/absolute/path/to/.grid-agent/runtime/pi/source
commit=2b3fda9921b5590f285165287bd442a25817f17b
lock_sha256=64-lowercase-hex-digest-of-lock-bytes
patches_sha256=64-lowercase-hex-digest-of-ordered-patch-identities
```

Do not modify or migrate existing `var/` data.

**Step 4: Run focused runtime tests**

```sh
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/runtime/test_installer.py \
  packages/grid-agent/tests/runtime/test_locator.py -q
```

Expected: PASS.

**Step 5: Exercise a real managed installation**

```sh
make install-pi
make doctor
```

Expected: installation builds the pinned source plus the verified patch;
`doctor` reports the managed `pi` executable as ready. This is non-billable.

**Step 6: Commit the installer slice**

```sh
git add configs/runtime/pi-runtime.lock.json \
  packages/grid-agent/src/grid_agent/runtime/lock.py \
  packages/grid-agent/src/grid_agent/runtime/installer.py \
  packages/grid-agent/tests/runtime/test_installer.py \
  packages/grid-agent/tests/runtime/test_locator.py
git commit -m "build: apply verified Pi runtime patches"
```

---

## Task 4: Prove the hook is usable by the project extension

**Files**

- Modify: `packages/pi-grid-tools/test/package.test.mjs`
- Modify: `packages/grid-agent/tests/e2e/test_semantic_pi_path.py`

**Step 1: Add a package-surface assertion**

Compile/load a minimal extension registering `before_model_request`. Assert the
managed Pi runtime accepts the event while the project tool surface remains
limited to the existing grid tools, `grid_guide_open`, and
`grid_submit_answer`.

**Step 2: Add a scripted pre-call order assertion**

Extend the scripted Pi fixture to emit a marker when the canonical hook runs and
when its fake provider begins. Assert canonical commitment precedes provider
entry. This test must not invent provider payload fields.

**Step 3: Run the cross-boundary tests**

```sh
npm test --prefix packages/pi-grid-tools
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/e2e/test_semantic_pi_path.py -q
```

Expected: PASS.

**Step 4: Commit the integration proof**

```sh
git add packages/pi-grid-tools/test/package.test.mjs \
  packages/grid-agent/tests/e2e/test_semantic_pi_path.py
git commit -m "test: prove canonical Pi request boundary"
```

---

## Plan verification checklist

Before declaring this prerequisite complete:

- The patch applies only to the exact locked upstream commit and is itself
  SHA-256 locked.
- The event contains final `Context`, selected `Model`, and only explicitly
  public options.
- Event objects are snapshots; observers cannot mutate the provider request.
- Observer failure prevents authentication/provider execution.
- No application code receives `before_provider_request.payload` as part of
  the new path.
- No provider-specific identifier such as `reasoning_content` appears in the
  new hook, tests, or public contract.
- Existing auth/header/provider behavior and stream-option defaults remain
  covered by regression tests.
- The patch is suitable for a standalone upstream PR; the installer mechanism
  is only the reproducible distribution method while the pinned upstream lacks
  the hook.
