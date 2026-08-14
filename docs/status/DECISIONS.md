# Architectural Decisions

## 2026-08-14 — Unified trajectory event spine and workbench

- **Status:** approved design; implementation not started
- **Decision:** make a typed, append-only, hash-chained native run event spine the authoritative chronology, with independent Agent, Business, Context, and Artifact projections.
- **Rationale:** the `v0.2` artifacts already prove execution and evidence but are split across related timelines. One durable chronology supports replay, exact model-input reconstruction, event-level context time travel, and a polished business-first workbench without weakening simulator or evidence authority.
- **Constraints:** DeepSeek Harness is prior art only; hidden chain-of-thought is excluded; historical runs remain immutable; the UI and API are read-only; numerical and network claims remain under `gridctl` and current-run evidence contracts.
- **Specification:** `docs/superpowers/specs/2026-08-14-unified-trajectory-workbench-design.md`
