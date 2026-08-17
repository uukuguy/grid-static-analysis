# Architectural Decisions

## 2026-08-17 — Unified LLM runtime boundary

- **Decision:** Provider-specific request and response fields remain exclusively
  inside `pi-ai` adapters. Pi exposes the final provider-independent invocation
  before network I/O, and trajectory records the exact canonical request rather
  than the raw provider payload.
- **Reason:** Raw `before_provider_request` capture made valid provider evolution
  capable of terminating the core `make analysis` flow. The repository already
  depends on a multi-provider normalization layer; the framework must consume its
  stable contract instead of duplicating provider logic.
- **Replay:** A request is durably committed before provider I/O with its canonical
  context, tools, public options, correlations, runtime/adapter versions, and hash.
  Wire-level diagnostics remain adapter-owned and non-authoritative.
- **Specification:**
  `docs/superpowers/specs/2026-08-17-unified-llm-runtime-boundary-design.md`

## 2026-08-14 — Unified trajectory event spine and workbench

- **Status:** approved design; implementation not started
- **Decision:** make a typed, append-only, hash-chained native run event spine the authoritative chronology, with independent Agent, Business, Context, and Artifact projections.
- **Rationale:** the `v0.2` artifacts already prove execution and evidence but are split across related timelines. One durable chronology supports replay, exact model-input reconstruction, event-level context time travel, and a polished business-first workbench without weakening simulator or evidence authority.
- **Constraints:** DeepSeek Harness is prior art only; hidden chain-of-thought is excluded; historical runs remain immutable; the UI and API are read-only; numerical and network claims remain under `gridctl` and current-run evidence contracts.
- **Specification:** `docs/superpowers/specs/2026-08-14-unified-trajectory-workbench-design.md`

## 2026-08-14 — Dependency-ordered trajectory delivery

- **Status:** approved plan; implementation not started
- **Decision:** deliver the platform through five gated plans in order: event spine, native capture, projections plus immutable `v0.2` import, loopback read-only API, then React Workbench.
- **Rationale:** each layer establishes a typed interface and focused regression gate before a consumer depends on it; the UI cannot become an alternate source of truth or force historical artifacts to be rewritten.
- **Technology boundary:** Python/Pydantic own chronology and replay; FastAPI/uvicorn expose fixed read-only loopback routes; React/TypeScript/Vite/TanStack Virtual implement the operator workbench; Vitest and Playwright cover interaction, accessibility, and visual states.
- **Roadmap:** `docs/superpowers/plans/2026-08-14-unified-trajectory-implementation-roadmap.md`
