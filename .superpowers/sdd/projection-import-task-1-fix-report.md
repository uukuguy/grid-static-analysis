# Projection-import Task 1 review follow-up

## Scope

Resolved the two Important review findings in the projection/import model boundary.

## Changes

- `ContextFrame`, `ArtifactIndexRecord`, and `ProjectionDiagnostic` now inherit the
  shared projection-node identity and provenance validation: a nonempty `id` and
  nonempty, strictly positive `source_sequences` are mandatory.
- Derived-rule validation remains where that semantic field exists:
  `BusinessNode` continues to require both `rule_id` and provenance for derived
  nodes. The affected context, artifact, and diagnostic records do not have a
  derivation-rule field.
- Imported event payloads and all projected context-state mappings are recursively
  frozen. Mappings reject in-place mutation and sequences are tuples, while
  `model_dump(mode="json")` continues to produce the established JSON object/array
  shape.

## TDD evidence

RED tests were added first and failed as expected for optional/defaulted node
identity/provenance and mutable nested imported payload/context state. A separate
checkpoint-state regression also failed before its freeze validator was added.

GREEN verification:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_service.py -q
# 10 passed
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory -q
# 122 passed
uv run --project packages/grid-agent ruff check packages/grid-agent/src/grid_agent/trajectory/replay.py packages/grid-agent/src/grid_agent/trajectory/projection_models.py packages/grid-agent/tests/trajectory/test_service.py
# All checks passed
uv run --project packages/grid-agent pyright packages/grid-agent/src/grid_agent/trajectory/replay.py packages/grid-agent/src/grid_agent/trajectory/projection_models.py packages/grid-agent/tests/trajectory/test_service.py
# 0 errors, 0 warnings
```
