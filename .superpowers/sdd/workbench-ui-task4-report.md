# Workbench UI Task 4 Report

## Scope

Implemented the approved Agent, Context, and Evidence drill-down views only.
The work is read-only: artifact links use the existing same-origin download
route, all documents render as React text nodes, and relationships are built
only from typed projection fields and declared refs.

## TDD evidence

- RED: `npm test --prefix packages/trajectory-workbench -- DrilldownViews`
  failed because `AgentView`, `ContextView`, and `EvidenceView` did not exist.
- GREEN: added focused tests for request timing/retries/paired tools, context
  before-delta-after with legacy unavailability, and keyboard evidence
  treegrid navigation. The focused App and drill-down gate passed 12 tests.

## Delivered

- Agent hierarchy with stable lifecycle IDs, source sequences, retries, TTFT,
  timing, tokens, tool outcomes, and registered artifact links.
- Context time travel with sequence scrubber, escaped Before/Delta/After
  documents, request input artifact, and explicit unavailable reason.
- Accessible evidence treegrid with bidirectional declared ref relations,
  textual source/integrity labels, keyboard row movement, and artifact links.
- App integration that lazily requests agent/context projections and derives
  the evidence display from typed business projection refs only; answer prose
  is never parsed.

## Verification

```text
npm test --prefix packages/trajectory-workbench        # 24 passed
npm run check --prefix packages/trajectory-workbench   # passed
npm run build --prefix packages/trajectory-workbench   # passed
```

No Playwright, visual-baseline, backend API, or release orchestration work was
performed; those belong to later plan tasks.
