# Provider Request Capture Compatibility Implementation Plan

**Goal:** Restore `make analysis` compatibility with Pi payloads containing
`undefined` without weakening exact native request replay.

**Architecture:** Normalize the in-memory provider payload into the same JSON
tree transmitted by JavaScript JSON serialization before existing validation
and immutable persistence. The capture hook continues to reject values that
have no safe JSON representation.

## Task 1: Canonicalize JSON-compatible Pi request payloads

**Files**

- Modify: `packages/pi-grid-tools/src/trajectory-capture.mjs`
- Test: `packages/pi-grid-tools/test/trajectory-capture.test.mjs`

**Steps**

1. Add a failing Node test with nested object `undefined` and array
   `undefined`, asserting the persisted artifact matches JSON serialization.
2. Run that test and confirm the current `non-JSON provider payload value`
   failure.
3. Add the smallest recursive canonicalizer; preserve existing rejection of
   non-finite numbers, `BigInt`, cycles, sparse arrays, non-plain objects,
   credential keys, and hidden-reasoning keys.
4. Run the complete Node capture suite and the Python runtime/analysis
   regression suite.
5. Commit only the code and test changes; leave user-owned state-file changes
   untouched.
