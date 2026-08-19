# Loopback Provider Proxy Bypass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically add a configured loopback LLM host to the Pi child process's `NO_PROXY` without changing external-provider proxy routing.

**Architecture:** Keep proxy policy in `build_pi_environment()`, the shared Pi process boundary used by all CLI entry points. Parse the validated resolved Base URL, recognize only `localhost` and loopback IP literals, and merge the exact host into the inherited uppercase `NO_PROXY` list.

**Tech Stack:** Python 3.11+, standard-library `ipaddress` and `urllib.parse`, pytest.

## Global Constraints

- Apply automatic proxy bypass only to loopback targets.
- Preserve existing `NO_PROXY`, `HTTP_PROXY`, and `HTTPS_PROXY` values.
- Do not relax non-loopback HTTP URL validation.
- Do not change provider/API selection, credentials, argv, or stdout output.

---

### Task 1: Merge the loopback provider host into Pi `NO_PROXY`

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/runtime/environment.py`
- Test: `packages/grid-agent/tests/runtime/test_provider_adapters.py`

**Interfaces:**
- Consumes: `ResolvedLLM.config.base_url: str` and the approved child environment mapping.
- Produces: `_merge_loopback_no_proxy(environment: dict[str, str], base_url: str) -> None`.

- [x] **Step 1: Write failing runtime tests**

Add parameterized cases proving that no existing value creates `NO_PROXY`, an
existing list is preserved, duplicates are avoided, IPv4/IPv6 loopback
addresses work, and an external URL leaves the environment unchanged.

- [x] **Step 2: Run the focused tests and verify RED**

Run:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_provider_adapters.py -q
```

Expected: the new loopback cases fail because the child environment does not
yet synthesize `NO_PROXY`.

- [x] **Step 3: Implement the minimal runtime merge**

Use `urlparse(base_url).hostname` and `ip_address(host).is_loopback`; recognize
`localhost` without DNS resolution. Split existing entries on commas, strip
empty entries, compare host entries case-insensitively, append only when absent,
and write the joined value back only for a loopback host.

- [x] **Step 4: Verify focused and broader tests GREEN**

Run:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_provider_adapters.py -q
make test-agent
```

Expected: all focused tests and the complete grid-agent suite pass.

- [x] **Step 5: Verify the actual local-provider route**

Run the existing `.env` configuration while retaining external proxy variables:

```sh
make run-llm QUESTION='只回答 OK。'
```

Expected: Pi reaches the local provider without requiring shell `NO_PROXY` and
does not fail immediately with `Connection error.`

- [x] **Step 6: Commit the isolated implementation**

```sh
git add packages/grid-agent/src/grid_agent/runtime/environment.py \
  packages/grid-agent/tests/runtime/test_provider_adapters.py \
  docs/superpowers/plans/2026-08-19-loopback-provider-proxy-bypass.md
git commit -m "fix: bypass proxies for loopback LLM providers"
```
