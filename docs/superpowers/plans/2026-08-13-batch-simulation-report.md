# Batch Simulation Report Implementation Plan

**Goal:** Run a line-oriented question set through the Pi/LLM path and produce an auditable, readable simulation-analysis report plus optional JSONL envelopes.

**Architecture:** Add a `grid-agent report` batch command that runs existing single-question `grid-agent run` sequentially, forwards its stderr for live observation, then renders report data from each current-run trace and evidence directory. Keep the single-question JSON contract unchanged.

**Constraints:** `run-llm` remains the primary execution path; no hidden chain-of-thought is persisted; reports describe observed tools, timings, environment metadata, result/evidence refs, and final answers only.

### Task 1: Report data and renderer

- [ ] Add tests for question-file parsing, trace timing extraction, readable Markdown, and JSONL envelopes.
- [ ] Add a focused report module using standard-library JSON/Markdown text generation.

### Task 2: Batch CLI and Makefile

- [ ] Add tests using a fake single-run subprocess for sequential execution, stdout forwarding, failure continuation, and optional JSONL output.
- [ ] Add `grid-agent report`, `make report`, the default TASK question file, and documentation.
- [ ] Verify focused tests, `make help`, and formatting checks.
