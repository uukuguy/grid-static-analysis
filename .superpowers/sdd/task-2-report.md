# Task 2 Report: Emit Canonical Pi Request Hook at Invocation Boundary

## Scope

- Modified only the patch artifact:
  `configs/runtime/patches/pi-0.80.6-before-model-request.patch`
- Upstream files represented by the patch:
  - `packages/coding-agent/src/core/sdk.ts`
  - `packages/coding-agent/test/sdk-before-model-request.test.ts`
  - Existing Task 1 extension contract/projector hunks are preserved.
- Did not implement Task 3 lock or installer changes.

## Implementation

- Extended the upstream `sdk-before-model-request.test.ts` patch with a provider matrix:
  `openai-completions` and `anthropic-messages`.
- The matrix asserts that the observed canonical event shape is provider-neutral and differs only by `model.api`.
- The observer snapshots the public event and then mutates its received context snapshot. The provider still receives the original final `Context`, proving observation-only behavior.
- Added `sdk.ts` helpers:
  - `resolvePublicRequestOptions()`
  - `publicModelRequestOptions()`
  - local `omitUndefined()`
- `streamFn` now resolves timeout/retry defaults before auth, emits `before_model_request` before `modelRegistry.getApiKeyAndHeaders(model)`, and reuses the same resolved values in the later `streamSimple()` call.
- Public request options are copied field-by-field and do not spread raw `SimpleStreamOptions`.

## TDD Evidence

### RED

Command:

```sh
npm test --workspace @earendil-works/pi-coding-agent -- sdk-before-model-request.test.ts
```

Result: expected failure after adding Task 2 tests, before `sdk.ts` implementation.

Key failure:

```text
AssertionError: expected [ 'provider' ] to deeply equal [ 'before_model_request', 'provider' ]
```

The handler-failure test also failed because `streamFn` resolved instead of rejecting with `commit failed`.

### GREEN

Command:

```sh
npm test --workspace @earendil-works/pi-coding-agent -- sdk-before-model-request.test.ts
```

Result:

```text
Test Files  1 passed (1)
Tests  6 passed (6)
```

## Verification

Clean patch apply from pinned Pi commit:

```sh
git apply --check configs/runtime/patches/pi-0.80.6-before-model-request.patch
git apply configs/runtime/patches/pi-0.80.6-before-model-request.patch
```

Result: passed on clean checkout of `2b3fda9921b5590f285165287bd442a25817f17b`.

Focused upstream tests from clean-applied checkout:

```sh
npm ci
npm test --workspace @earendil-works/pi-coding-agent -- \
  sdk-before-model-request.test.ts sdk-stream-options.test.ts
```

Result:

```text
Test Files  2 passed (2)
Tests  11 passed (11)
```

Format/lint check for modified upstream files:

```sh
npx biome check packages/coding-agent/src/core/sdk.ts \
  packages/coding-agent/test/sdk-before-model-request.test.ts
```

Result:

```text
Checked 2 files in 10ms. No fixes applied.
```

Patch whitespace check from clean-applied checkout:

```sh
git diff --check
```

Result: passed.

Full Pi build:

```sh
npm run build
```

Result: blocked by external/generated-catalog failure before `coding-agent` build. `packages/ai/scripts/generate-models.ts` timed out fetching `https://models.dev/api.json`, generated only 9 provider catalogs, and `pi-ai` then failed with missing generated provider modules such as `./anthropic.models.ts`, `./google.models.ts`, and `./github-copilot.models.ts`.

## Notes

- The build failure is upstream generator/network related and reproducible in fresh clean-applied checkouts.
- No generated files from failed build attempts were copied into the repository patch artifact.
- Existing unrelated local changes remained untouched:
  - `.superpowers/sdd/task-1-report.md`
  - `docs/status/JOURNAL.md`
