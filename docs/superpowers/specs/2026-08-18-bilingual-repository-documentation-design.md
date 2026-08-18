# Bilingual Repository Documentation and Agent Contract Design

**Date:** 2026-08-18
**Status:** Approved for implementation

## 1. Goal

Align the repository entry points and GitHub metadata with the `v1.0.0`
product while keeping stable project contracts separate from frequently changing
release, capability, and operational details.

The documentation must serve operators and contributors equally: a new user
should be able to understand the product and run one analysis quickly, while a
developer or coding agent should be able to find the authoritative architecture,
boundary, and verification sources without reading the implementation first.

## 2. Scope

This change will:

1. Rewrite `README.md` as the default English repository entry point.
2. Add `README.zh-CN.md` as a section-aligned Simplified Chinese edition.
3. Rewrite `AGENTS.md` as the stable, tool-neutral contract for Codex and Claude
   Code.
4. Add the relative symbolic link `CLAUDE.md -> AGENTS.md`.
5. Set the GitHub repository About description and Topics, then read them back
   for verification.

This change will not alter runtime behavior, capability definitions, simulator
results, evidence, release tags, repository visibility, or provider credentials.

## 3. Documentation Architecture

### 3.1 Repository entry points

`README.md` is the default landing page and is written in English.
`README.zh-CN.md` mirrors the same headings, facts, commands, and references in
Simplified Chinese. Each file begins with a direct language switch to the other.

Both README files use this information order:

1. Product identity and one-paragraph value proposition.
2. Stable highlights and the distinction between the declared static-analysis
   scope and the entire public pandapower API.
3. A short architecture path from natural-language question to `grid-agent`,
   `gridctl`, pandapower, results, evidence, and the answer envelope.
4. Prerequisites and quick start.
5. Primary workflows: offline smoke check, LLM-led single question, continuous
   analysis/report, and the read-only trajectory workbench.
6. Output, evidence, and security boundaries.
7. Verification commands.
8. Repository layout and authoritative documentation index.

The README files may state that `v1.0.0` is the first stable release, but they
must not duplicate mutable coverage counts, model counts, provider defaults, or
long command references. Those facts remain in their authoritative sources.

### 3.2 Stable coding-agent contract

`AGENTS.md` is the single source for repository-wide coding-agent instructions.
Its language is compatible with both Codex and Claude Code and does not depend
on product-specific agent features.

It contains only stable global rules:

- product and stdout envelope contract;
- simulator ownership and the `grid-capability/1.0` boundary;
- prohibition on guessed network facts;
- allowlisted LLM tool boundary;
- current-run evidence requirements;
- runtime, credential, and working-tree safety;
- documentation source-of-truth map;
- focused-first and full-gate verification policy;
- bilingual README synchronization rule.

Frequently changing information is referenced rather than copied:

| Information | Authoritative source |
| --- | --- |
| Published capability coverage | `configs/capabilities/pandapower-3.4.0-static-analysis.json` |
| Simulator package/version pin | `packages/grid-simulator/pyproject.toml` |
| Runtime operations and authentication | `docs/RUNBOOK.md` |
| Capability registration and composition | `docs/architecture/pandapower-capability-composition.md` |
| Model-facing execution policy | `configs/agent/system-policy.md` |
| Structural project state | `docs/status/CURRENT-STATE.md` |
| Session recovery baton | `docs/status/RESUME-NEXT-SESSION.md` |

`CLAUDE.md` is a relative symbolic link to `AGENTS.md`. It must not be a copied
file because copied instructions would create two mutable sources of truth.

## 4. README Content Contract

The bilingual pair must communicate these product facts consistently:

- `grid-agent` is a capability-first CLI agent for registered power-system
  networks.
- Numerical and network-specific claims are calculated behind `gridctl`; the LLM
  interprets intent and composes registered tools.
- The release covers the project's declared pandapower static-analysis scope,
  not every public pandapower Python API.
- The CLI preserves the single JSON stdout envelope; diagnostics use stderr.
- Simulator-backed answers persist operator-visible current-run evidence under
  `runs/`; internal runtime and authentication state stays under `.grid-agent/`.
- The trajectory workbench is read-only and does not become a second source of
  simulator truth.
- Provider-backed validation is optional, credential-dependent, and potentially
  billed.

Commands shown in the quick start must come directly from the Makefile and must
not imply that an LLM provider is required for offline smoke checks.

## 5. GitHub Metadata

The About description will be:

> Capability-first CLI agent for evidence-backed power-system static analysis with pandapower.

The Topics set will be:

- `power-systems`
- `power-grid`
- `pandapower`
- `static-analysis`
- `power-flow`
- `optimal-power-flow`
- `short-circuit`
- `contingency-analysis`
- `state-estimation`
- `llm-agent`
- `ai-agent`
- `python`
- `cli`
- `electrical-engineering`

The update must preserve the current repository visibility and must not set a
homepage URL unless the user separately supplies one.

## 6. Failure Handling

- A missing local README reference blocks the documentation commit.
- A mismatch between English and Chinese heading structure blocks completion.
- A non-symbolic `CLAUDE.md`, an absolute symlink, or a target other than
  `AGENTS.md` blocks completion.
- If GitHub authentication, permission, or network access prevents metadata
  synchronization, the local documentation may still be committed, but the
  final report must mark the GitHub update as incomplete.
- Existing unrelated tracked or untracked workspace files must not be staged,
  deleted, or rewritten.

## 7. Verification

The implementation is accepted when all of the following are true:

1. `README.md` is English by default and links to `README.zh-CN.md`.
2. `README.zh-CN.md` links back to `README.md`, and both files have the same
   section hierarchy.
3. Every repository-relative Markdown link in the three documentation files
   resolves.
4. `test -L CLAUDE.md` succeeds and `readlink CLAUDE.md` returns `AGENTS.md`.
5. Reading `CLAUDE.md` and `AGENTS.md` produces identical bytes.
6. Quick-start and verification commands agree with the Makefile.
7. `git diff --check` succeeds.
8. `make doctor` succeeds; broader runtime gates are run only if implementation
   changes extend beyond documentation and metadata.
9. `gh repo view` returns the approved About description and the complete Topics
   set after the update.
10. The final staged/committed file list excludes all unrelated workspace
    artifacts.

## 8. Non-goals

- Changing public/private repository visibility.
- Publishing or moving `v1.0.0`.
- Adding badges that depend on nonexistent CI, package registries, or licenses.
- Introducing a new documentation generator or translation toolchain.
- Duplicating the runbook, architecture documents, capability matrix, or project
  state inside the README files.
