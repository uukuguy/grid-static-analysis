# Workbench older-page error follow-up

## Scope

Fixed the business trajectory's older-cursor error path in `App.tsx`.

- Preserve the raw older-page error in the business page error state, so an
  `ApiError` with status `501` renders the unsupported state.
- Retain the failed cursor only while that cursor load has failed.
- Route the generic Retry control to that failed cursor instead of triggering
  the initial business-page effect.
- Clear the retained cursor on a successful initial or older-page load.

## TDD evidence

RED:

```text
npm test -- src/app/App.test.tsx
24 tests: 2 failed
- older-cursor HTTP 501 rendered network-error because the raw error was discarded
- retry rendered the generic older-page error and did not preserve the failed cursor
```

GREEN:

```text
npm test -- src/app/App.test.tsx
24 passed
```

The added focused cases cover an older cursor returning raw `ApiError(501)`
and a retryable older-cursor error whose retry requests `older-page`, not the
initial page.

## Verification

```text
npm test      42 passed
npm run check passed
npm run build passed
npm run test:e2e collected 15 tests; 13 passed, 2 failed
```

The two E2E failures are shared Task 5 scenarios left outside this follow-up's
owned source/test scope:

- `100k trajectory remains cursor-paginated and mounts a bounded row window`
- `all trajectory states remain useful and non-destructive`
