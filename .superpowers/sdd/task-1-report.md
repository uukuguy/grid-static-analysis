# Task 1 Report: Pi before_model_request Contract

## Summary

Created an upstream-ready patch artifact at `configs/runtime/patches/pi-0.80.6-before-model-request.patch` against Pi `0.80.6` commit `2b3fda9921b5590f285165287bd442a25817f17b`.

The patch defines the provider-neutral, observation-only `before_model_request` extension event contract, adds a fail-closed `ExtensionRunner.emitBeforeModelRequest()` method, re-exports the public types, and adds SDK boundary tests that describe the required emission behavior for the next task.

No installed `.grid-agent/runtime/pi/source` tree was edited. Work was performed in a clean temporary checkout: `/tmp/pi-canonical-hook.G6C55q/pi`.

## Files Changed

Repository:

- `configs/runtime/patches/pi-0.80.6-before-model-request.patch`

Upstream files represented in the patch:

- `packages/coding-agent/src/core/extensions/types.ts`
- `packages/coding-agent/src/core/extensions/runner.ts`
- `packages/coding-agent/src/core/extensions/index.ts`
- `packages/coding-agent/src/index.ts`
- `packages/coding-agent/test/sdk-before-model-request.test.ts`

## RED Evidence

Command:

```sh
npm test --workspace @earendil-works/pi-coding-agent -- sdk-before-model-request.test.ts
```

Result before implementation: FAIL, 2 failed tests.

Observed failures:

- First test received order `["provider"]` instead of `["before_model_request", "provider"]`.
- Second test resolved with `AssistantMessageEventStream` instead of rejecting with `commit failed`; provider call was not blocked.

This proves the test catches the missing pre-provider SDK emission behavior.

## GREEN / Verification Evidence

Contract implementation and formatting:

```sh
npx biome check packages/coding-agent/src/core/extensions/types.ts packages/coding-agent/src/core/extensions/runner.ts packages/coding-agent/src/core/extensions/index.ts packages/coding-agent/src/index.ts packages/coding-agent/test/sdk-before-model-request.test.ts
```

Result: PASS, `Checked 5 files in 13ms. No fixes applied.`

Upstream dependency/type build:

```sh
cd packages/ai && npx tsgo -p tsconfig.build.json
```

Result: PASS.

Coding-agent build/typecheck after building local workspace dependencies:

```sh
npm run build --workspace @earendil-works/pi-agent-core && npm run build --workspace @earendil-works/pi-coding-agent
```

Result: PASS.

Patch hygiene:

```sh
git apply --check configs/runtime/patches/pi-0.80.6-before-model-request.patch
```

Result against a fresh pinned checkout: PASS, patch applies cleanly.

```sh
git diff --check -- configs/runtime/patches/pi-0.80.6-before-model-request.patch
```

Result: PASS, no whitespace errors.

Expected remaining behavior test status after contract-only implementation:

```sh
npm test --workspace @earendil-works/pi-coding-agent -- sdk-before-model-request.test.ts
```

Result: FAIL, 2 failed tests, because SDK stream-boundary emission is intentionally not implemented in this task.

## Self-Review

- The event options type includes only semantic replay inputs requested in the brief: reasoning, thinking budgets, temperature, max tokens, transport, cache retention, timeouts, and retry controls.
- The event excludes private/transport/correlation fields in the tests: `apiKey`, `env`, `headers`, `signal`, `onPayload`, `onResponse`, `metadata`, and `sessionId`.
- `emitBeforeModelRequest()` projects safe public model/context/options snapshots before each handler.
- Handler failures propagate naturally because the method does not catch/log like display-oriented extension events.
- No SDK emission wiring was added, preserving the task boundary for the next slice.

## Concerns

- The exact SDK behavior tests remain failing by design until Task 2 calls `emitBeforeModelRequest()` at the stream boundary.
- A root `npm run build` attempt was blocked before coding-agent by `packages/ai` online model generation/network-derived generated files. After restoring generated files, focused dependency and coding-agent builds passed.

## Review Fix: Safe Public Projection

Review found two Important issues in the first patch artifact:

- `structuredClone(context)` would throw `DataCloneError` for real `Context.tools` containing executable callbacks.
- `structuredClone(options)` would clone runtime/private fields instead of selecting only the public semantic request options.

Fix applied in the upstream patch:

- Added `PublicModelRequestTool` and `PublicModelRequestContext`.
- Changed `BeforeModelRequestEvent.context` from full `Context` to the safe public context snapshot.
- Added `projectBeforeModelRequestContext()` to copy system prompt, converted messages, and tool `name`/`description`/`parameters` only.
- Added `projectPublicModelRequestOptions()` to select exactly the Task 1 public option fields.
- Added direct runner-contract tests without SDK emission wiring.

### Review RED Evidence

Command:

```sh
npm test --workspace @earendil-works/pi-coding-agent -- sdk-before-model-request.test.ts -t "tool snapshot|public semantic"
```

Result before fix: FAIL, 2 failed tests.

Observed failures:

- Tool snapshot test failed with `DataCloneError: async () => ({ result: "[]" }) could not be cloned.`
- Public-options test failed with `DataCloneError: () => undefined could not be cloned.`

### Review GREEN Evidence

Command:

```sh
npm test --workspace @earendil-works/pi-coding-agent -- sdk-before-model-request.test.ts -t "tool snapshot|public semantic"
```

Result after fix: PASS, `Test Files 1 passed (1)`, `Tests 2 passed | 2 skipped (4)`.

Full contract test file:

```sh
npm test --workspace @earendil-works/pi-coding-agent -- sdk-before-model-request.test.ts
```

Result after fix: expected FAIL, `Tests 2 failed | 2 passed (4)`. The two passing tests cover safe runner projection; the two failing tests are still the Task 2 SDK-emission expectations.

Formatting:

```sh
npx biome check packages/coding-agent/src/core/extensions/types.ts packages/coding-agent/src/core/extensions/runner.ts packages/coding-agent/src/core/extensions/index.ts packages/coding-agent/src/index.ts packages/coding-agent/test/sdk-before-model-request.test.ts
```

Result: PASS, `Checked 5 files in 13ms. No fixes applied.`

Build/typecheck:

```sh
npm run build --workspace @earendil-works/pi-agent-core && npm run build --workspace @earendil-works/pi-coding-agent
```

Result: PASS.

Patch apply:

```sh
git apply --check configs/runtime/patches/pi-0.80.6-before-model-request.patch
```

Result against a fresh pinned checkout: PASS, patch applies cleanly.

Upstream source whitespace:

```sh
git diff --cached --check
```

Result in the temporary upstream checkout: PASS, no whitespace errors.

## Second Review Fix: Public Model Identity

Second review found that `BeforeModelRequestEvent.model` still exposed `structuredClone(model)`, which can include provider-private model fields such as `headers`, `compat`, `baseUrl`, and other non-semantic configuration.

Fix applied in the upstream patch:

- Added `PublicModelRequestModel`.
- Changed `BeforeModelRequestEvent.model` from full `Model<Api>` to `PublicModelRequestModel`.
- Added `projectBeforeModelRequestModel()` to expose only `provider`, `api`, and `id`.
- Updated the fixture model to include `headers` and `compat`.
- Added a direct runner-contract test proving the observer receives only model identity and not private/provider fields.
- No SDK stream-boundary emission was added.

### Second Review RED Evidence

Command:

```sh
npm test --workspace @earendil-works/pi-coding-agent -- sdk-before-model-request.test.ts -t "public semantic identity"
```

Result before fix: FAIL, 1 failed test.

Observed failure:

- `observed.model` contained full model fields including `headers`, `compat`, `baseUrl`, `name`, `cost`, `contextWindow`, and `maxTokens` instead of only `{ provider, api, id }`.

### Second Review GREEN Evidence

Command:

```sh
npm test --workspace @earendil-works/pi-coding-agent -- sdk-before-model-request.test.ts -t "public semantic identity"
```

Result after fix: PASS, `Test Files 1 passed (1)`, `Tests 1 passed | 4 skipped (5)`.

Projection regression tests:

```sh
npm test --workspace @earendil-works/pi-coding-agent -- sdk-before-model-request.test.ts -t "tool snapshot|public semantic"
```

Result after fix: PASS, `Test Files 1 passed (1)`, `Tests 3 passed | 2 skipped (5)`.

Full contract test file:

```sh
npm test --workspace @earendil-works/pi-coding-agent -- sdk-before-model-request.test.ts
```

Result after fix: expected FAIL, `Tests 2 failed | 3 passed (5)`. The three passing tests cover model/context/options projection; the two failing tests remain the Task 2 SDK-emission expectations.

Formatting:

```sh
npx biome check packages/coding-agent/src/core/extensions/types.ts packages/coding-agent/src/core/extensions/runner.ts packages/coding-agent/src/core/extensions/index.ts packages/coding-agent/src/index.ts packages/coding-agent/test/sdk-before-model-request.test.ts
```

Result: PASS, `Checked 5 files in 13ms. No fixes applied.`

Build/typecheck:

```sh
npm run build --workspace @earendil-works/pi-agent-core && npm run build --workspace @earendil-works/pi-coding-agent
```

Result: PASS.

Patch apply:

```sh
git apply --check configs/runtime/patches/pi-0.80.6-before-model-request.patch
```

Result against a fresh pinned checkout: PASS, patch applies cleanly.

Upstream source whitespace:

```sh
git diff --cached --check
```

Result in the temporary upstream checkout: PASS, no whitespace errors.
