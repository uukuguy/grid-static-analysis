# Loopback Provider Proxy Bypass Design

## Problem

`grid-agent` deliberately forwards `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY`
to the managed Pi process. When an operator selects an OpenAI-compatible local
service such as `http://localhost:11234/v1`, an existing external proxy is also
applied to that loopback request unless the operator has manually configured
`NO_PROXY`. The local service and its Responses endpoint can both be healthy,
while Pi reports only `Connection error.` before receiving any tokens.

Requiring a shell-specific `NO_PROXY` edit makes a valid project configuration
fail differently across operator environments. Fixing only Makefile recipes
would leave direct `grid-agent` and `uv run` invocations broken.

## Goals

- Make every grid-agent entry point reach configured loopback LLM services
  directly, even when external HTTP proxies are configured.
- Preserve the operator's existing `NO_PROXY` entries.
- Keep external providers such as OpenRouter on the existing proxy path.
- Apply the behavior only to loopback targets.

## Non-goals

- Bypassing proxies for private LAN, link-local, or public provider addresses.
- Relaxing the existing rule that non-loopback HTTP base URLs are rejected.
- Changing provider selection, API compatibility profiles, authentication, or
  the CLI stdout envelope.
- Making the Makefile the source of runtime network policy.

## Design

`build_pi_environment()` remains the single boundary that constructs the Pi
child-process environment. After copying the approved proxy variables from the
parent environment, it parses the already validated resolved provider base URL.

If the URL host is `localhost` or an IP address for which Python's
`ipaddress.ip_address(host).is_loopback` is true, the runtime appends that exact
host to `NO_PROXY`. Existing comma-separated entries are retained in their
original order, empty entries are discarded, and an already present exact
entry is not duplicated. When no `NO_PROXY` exists, the runtime creates one
containing only the configured loopback host.

For any non-loopback host, including OpenRouter and other external HTTPS
providers, the runtime leaves `NO_PROXY` unchanged. It does not resolve DNS or
infer whether a hostname maps to a private network.

Only uppercase `NO_PROXY` is required in the Pi environment because that is the
project's existing approved proxy variable. The runtime does not add lowercase
environment variables or mutate the parent process.

## Data Flow

1. Configuration resolution validates and stores the provider Base URL.
2. The CLI constructs a `ResolvedLLM` and calls `build_pi_environment()`.
3. The runtime copies allowed environment variables from the parent process.
4. The runtime conditionally merges the resolved loopback host into the Pi
   child's `NO_PROXY` value.
5. Pi connects directly to the local service; unrelated external requests keep
   using the inherited proxy configuration.

## Failure and Compatibility Behavior

Malformed URLs remain the configuration resolver's responsibility and do not
receive special handling here. IPv4 and IPv6 loopback literals are supported.
The existing exact value and ordering of other `NO_PROXY` entries are preserved
so the change does not widen proxy bypass unexpectedly.

This change fixes transport routing only. A local service must still implement
the selected provider API profile, streaming, and tool calling required by
`grid-agent`.

## Verification

Focused runtime tests will establish that:

- a loopback Base URL creates `NO_PROXY` when the parent has none;
- a loopback host is appended to existing exclusions without removing them;
- an already present host is not duplicated;
- IPv4 and IPv6 loopback literals are recognized;
- an external OpenRouter Base URL leaves proxy settings unchanged;
- `HTTP_PROXY` and `HTTPS_PROXY` continue to be inherited;
- secrets remain outside argv and the stdout envelope is unaffected.

The focused runtime test file runs first, followed by the broader grid-agent
test gate appropriate to this isolated behavior change.
