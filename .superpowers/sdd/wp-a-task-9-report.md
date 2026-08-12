# WP-A Task 9 Review Fix Report

## Scope

- Worktree: `/Users/sujiangwen/sandbox/LLM/speechless.ai/SGAI/grid-static-analysis/.worktrees/pandapower-semantic-capabilities`
- Branch: `feature/pandapower-semantic-capabilities`
- Baseline: `d8143c054dacab2853be3982d7342fb6fcb5e8bb` (`Expose semantic grid tools to Pi`)
- Fix commit: `5e5fc027e41aaf3ec4b57e175fa47280c13cab1b` (`Defend domain tool paths by resolved target`)
- Files changed in fix commit:
  - `packages/pi-grid-tools/src/domain-tools.mjs`
  - `packages/pi-grid-tools/test/domain-tools.test.mjs`

## Review Finding Addressed

- `domain-tools.mjs` previously used lexical `resolve()` plus `relative()` containment checks for configured startup paths and guide resources.
- A path that looked inside the workspace or guide root could still be a symlink to an outside target.
- The fix resolves real filesystem targets before containment and reads only the validated real target.

## TDD Evidence

- RED command: `npm test --prefix packages/pi-grid-tools -- test/domain-tools.test.mjs`
- RED result: failed as expected with 2 failures:
  - `guide tool rejects lexically allowed symlinks outside the published root` opened the outside guide instead of returning `isError`.
  - `startup rejects configured symlink paths that escape the workspace` did not throw for the catalog symlink.
- GREEN focused command: `npm test --prefix packages/pi-grid-tools -- test/domain-tools.test.mjs`
- GREEN focused result: `9 passed, 0 failed`.

## Implementation Summary

- Startup path validation now realpaths `GRID_AGENT_WORKSPACE`, `GRID_AGENT_TOOL_CATALOG`, and `GRID_AGENT_GUIDE_INDEX`.
- `GRID_AGENT_ANSWER_DRAFT` now resolves an existing draft target, or resolves its parent for normal not-yet-created atomic submission.
- Startup rejects catalog, guide-index, or answer-draft real targets outside the real workspace path.
- Registered grid tools pass the validated real workspace path to `gridctl` instead of re-reading an unvalidated env value.
- `grid_guide_open` now realpaths the published guide root and candidate guide resource before containment and before reading file content.
- The answer submission tool still writes through the existing temp-file plus `rename()` atomic path.

## Verification

- Focused RED: `npm test --prefix packages/pi-grid-tools -- test/domain-tools.test.mjs` -> failed for the two new symlink tests before the fix.
- Focused GREEN: `npm test --prefix packages/pi-grid-tools -- test/domain-tools.test.mjs` -> `9 passed, 0 failed`.
- Node syntax diagnostics substitute: `npm run check --prefix packages/pi-grid-tools` -> `node --check src/domain-tools.mjs` passed.
- Full suite: `make test` -> agent `115 passed`; simulator `78 passed, 18 warnings`; Node tools `10 passed`.
- E2E suite: `make test-e2e` -> `9 passed in 11.60s`.
- Diff whitespace: `git diff --check` -> passed.
- Debug scan: `rg -n "console\\.log|debugger|TODO|FIXME|outside guide secret|grid-domain-tools-outside" packages/pi-grid-tools/src/domain-tools.mjs packages/pi-grid-tools/test/domain-tools.test.mjs` -> matches only intentional test fixture strings, no debug leftovers.

## Concerns

- No LSP diagnostics tool was exposed in this session; Node `--check`, focused tests, full tests, and E2E were used as available diagnostics evidence.
- I did not update `docs/status/JOURNAL.md` despite the local lightweight-memory reminder because the task explicitly said `No main/docs/status`.
