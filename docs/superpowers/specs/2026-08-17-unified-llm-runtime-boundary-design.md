# Unified LLM Runtime Boundary Design

## Status

Approved direction on 2026-08-17. This specification corrects the
provider-payload capture architecture used by native trajectory runs and is the
authority for the LLM/runtime/trajectory boundary.

It supersedes the exact raw-provider-payload capture decision in
`2026-08-14-trajectory-native-capture.md` and the provider-payload normalization
approach in `2026-08-17-provider-request-capture-compatibility-design.md`. The
rest of those documents remains historical implementation context unless it
conflicts with this specification.

## Problem

`make analysis` is the product's core entry point. The current trajectory
implementation observes Pi's `before_provider_request` event and treats its raw,
provider-specific payload as a framework-owned request artifact. It recursively
validates that payload and terminates Pi when it sees a field that the trajectory
layer prohibits or cannot serialize.

This reverses the intended dependency direction. Fields such as DeepSeek's
`reasoning_content` are provider-adapter details. They are valid inputs to the
provider protocol and are already handled by `pi-ai`; they must not be interpreted
by grid-agent, the analysis runner, or the trajectory recorder.

The observed failures are consequences of that boundary violation:

1. JavaScript `undefined` in a provider payload stopped analysis before a tool
   call.
2. A valid Pi response-before-tool-execution order conflicted with a capture-state
   assumption.
3. DeepSeek's valid `reasoning_content` continuation field was rejected after two
   tools had completed.

Adding provider-field exceptions would preserve the error and make every provider
or SDK change a possible outage of `make analysis`.

## Research Finding

The repository already uses the reusable provider abstraction it needs:
`@earendil-works/pi-ai` 0.80.6. Its public contract includes provider-independent
`Context`, `Message`, `Tool`, `AssistantMessage`, `Usage`, `StopReason`, and
`AssistantMessageEvent` types. Its provider adapters own wire conversion,
including DeepSeek reasoning compatibility.

The missing abstraction is not another provider SDK. It is a small,
provider-independent invocation and observability boundary around `pi-ai`, placed
between the agent loop and provider adapters. That boundary must have one reusable
implementation rather than copies in each application's tracing code.

Alternative libraries do not improve the current fit:

- Vercel AI SDK is a capable TypeScript provider abstraction, but replacing
  `pi-ai` would duplicate a working dependency and disrupt the Pi runtime.
- LiteLLM is useful as a cross-language organizational gateway, but adds a
  service/protocol hop. It is an optional deployment gateway, not the required
  in-process semantic boundary.
- LangChain is a broader orchestration framework that overlaps with Pi and is
  larger than the required runtime port.

## Goals

- Keep provider-specific fields inside `pi-ai` adapters.
- Give applications one stable invocation contract and normalized event stream.
- Preserve exact, replayable model input without inspecting wire payloads.
- Ensure trajectory recording cannot reject a valid provider-private field.
- Require the current-run request artifact to be durably committed before its
  provider call begins.
- Preserve Pi's agent loop, project tool boundary, stdout envelope, and `gridctl`
  simulator boundary.
- Make the boundary suitable for one shared package used by multiple projects.

## Non-goals

- Reimplementing provider adapters supplied by `pi-ai`.
- Replacing Pi's agent/tool loop.
- Exposing raw provider payloads in Business, Agent, Context, or Evidence views.
- Persisting hidden chain-of-thought.
- Treating HTTP headers, credentials, SDK objects, or provider response bodies as
  portable replay input.
- Adding shell, filesystem, Python, or non-project tools to the model.

## Architectural Decision

Use a ports-and-adapters boundary with separate responsibilities:

```text
grid-agent analysis policy
        |
        v
Pi agent/tool loop
        |
        v
Unified LLM Runtime Port
  - canonical request identity
  - durable pre-call observation
  - normalized events, outcome, error, and usage
        |
        v
pi-ai provider adapters
  - authentication inputs
  - provider request conversion
  - provider-private continuation fields
  - response conversion and stream decoding
        |
        v
DeepSeek / OpenAI / Anthropic / other provider
```

Trajectory consumes the Unified LLM Runtime Port. It is not between `pi-ai` and
the provider and cannot inspect, modify, validate, or veto wire payloads.

## Reusable Runtime Contract

The shared contract is intentionally smaller than an agent framework. A
TypeScript representation is shown for clarity; package naming is a distribution
decision and does not change the contract.

```ts
interface LlmRuntime {
  invoke(request: CanonicalLlmRequest): LlmInvocation;
}

interface LlmInvocation {
  requestId: string;
  events: AsyncIterable<CanonicalLlmEvent>;
  result(): Promise<CanonicalLlmOutcome>;
}
```

`CanonicalLlmRequest` contains only stable, provider-independent fields:

- schema version and request ID;
- public provider, API, and model identifiers;
- canonical `pi-ai` context: system prompt, messages, and tools;
- normalized public inference options;
- analysis, turn, and context correlation metadata;
- runtime and adapter package versions.

It never contains credentials, HTTP headers, provider SDK objects, raw payloads,
or provider-private fields.

`CanonicalLlmEvent` covers request preparation and commitment, response start,
public text/thinking block lifecycle, tool-call lifecycle, normalized completion,
usage, stop reason, failure, and abort. The persisted trajectory schema remains
project-owned and versioned.

## Required Pi Integration Point

The current `before_provider_request(payload: unknown)` hook is too late and too
low-level. Pi must expose or use a provider-independent invocation point after all
agent context transformations and tool selection have completed, but before
`pi-ai` converts the canonical context to a provider payload.

The hook or wrapper receives read-only:

- the selected `pi-ai` model;
- the final `pi-ai Context` with system prompt, converted messages, and active tool
  schemas;
- normalized public stream options;
- a request correlation ID.

It must complete before `streamSimple` begins conversion or network I/O. If the
installed Pi runtime does not expose this boundary, the shared Pi runtime
package/fork must add it. Reconstructing the request from separate `context`,
`before_agent_start`, tool-list, or raw-payload events is not accepted because
those sources do not prove the exact final invocation object.

## Exact Input and Replay Semantics

The authoritative request artifact is the canonical request passed to the runtime,
not the generated HTTP body.

Before each provider call:

1. Assign the request ID and bind it to the analysis, turn, and context revision.
2. Canonically serialize the complete provider-independent request.
3. Validate that it contains no credentials or hidden reasoning.
4. Atomically write and fsync the immutable request artifact.
5. Append the matching native trajectory event.
6. Only then allow `pi-ai` conversion and network I/O.

The artifact records the `pi-ai` version, runtime version, public model metadata,
and SHA-256 digest. The recorded request plus adapter version reconstructs the same
semantic input while allowing the adapter to supply required private continuation
fields.

Byte-for-byte HTTP replay is not the trajectory contract. SDK defaults, generated
IDs, headers, timestamps, signatures, and transport encoding are neither stable nor
safe public inputs. Any future wire-level debugging must live inside the provider
adapter as an opt-in, redacted, access-controlled diagnostic with a separate
schema. It cannot drive trajectory projection or analysis control flow.

## Reasoning and Privacy

The runtime distinguishes public normalized thinking content from provider-private
continuation data:

- public `pi-ai` thinking blocks follow existing Agent-trajectory policy;
- opaque signatures and required continuation fields stay in adapter/session data;
- hidden chain-of-thought and provider-private fields are not copied into native
  trajectory artifacts;
- the framework has no provider-field allowlist or denylist.

Consequently, `reasoning_content` is neither accepted nor rejected by grid-agent;
grid-agent never sees it.

## Failure Semantics

- **Canonical request invalid:** reject before network I/O with a typed runtime
  contract error.
- **Request artifact cannot be committed:** reject before network I/O with a typed
  recorder-storage error, preserving evidence without billing an unrecorded call.
- **Provider conversion/request fails:** record a normalized provider failure
  against the committed request.
- **Response recording fails after network I/O:** stop the analysis with an explicit
  trajectory-integrity failure while retaining the durable prefix.
- **Unknown provider-private field:** remains adapter-owned and cannot independently
  trigger a grid-agent trajectory failure.

Process exit code 86 must not act as a provider-schema validator. It may remain a
temporary transport signal only for a genuine pre-call durability failure until
RPC exposes a typed error; no provider payload content is involved.

## Ownership Boundaries

### Shared LLM runtime

Owns canonical request/outcome/event contracts, correlation IDs, normalized errors,
usage, and pre-call observer sequencing. It depends on `pi-ai` and contains no grid
concepts.

### `pi-ai`

Owns provider/API selection, authentication inputs, compatibility flags, wire
payload generation, streaming response parsing, and normalized messages.

### Pi agent runtime

Owns conversation turns, context transformation, tool-loop decisions, compaction,
and calls to the shared runtime. It exposes the exact final canonical invocation.

### `grid-agent`

Owns instructions, analysis state, model capability policy, answer composition,
stdout envelope, and mapping normalized runtime events into the event spine.

### Trajectory recorder

Owns durable artifacts, hashes, causal relationships, projections, and integrity.
It consumes canonical events and never imports provider protocol knowledge.

### `gridctl`

Continues to own deterministic simulator operations through `grid-capability` 1.0.
This design does not change that trust boundary.

## Package Reuse Strategy

The runtime has one implementation source in a dedicated shared package layered on
`pi-ai`. Until publication, the contract may be developed in one workspace package
and consumed through a normal dependency, but application-local provider adapters
are prohibited. Projects may add application observers and policies outside the
runtime; those observers may not branch on provider formats.

Optional gateways such as LiteLLM remain deployment choices behind the same port.

## Migration

1. Define and test canonical request, event, outcome, and error contracts in the
   shared boundary.
2. Add the provider-independent pre-invocation point to Pi and prove it runs after
   final context conversion and before `pi-ai` network I/O.
3. Make native capture consume canonical requests/events.
4. Remove trajectory registration for `before_provider_request` and delete its
   provider-payload normalization and denylist logic.
5. Replace `provider_payload` artifacts with a versioned canonical-request artifact
   and update projections/read APIs without exposing raw artifacts.
6. Keep explicit legacy import semantics; old runs remain readable and immutable.
7. Run focused contract tests, full Makefile gates, then one explicitly authorized
   live-provider verification.

There is no compatibility mode in which new runs silently omit request input. A new
run either commits the complete canonical request before the call or does not issue
that call.

## Testing Strategy

### Shared runtime

- identical canonical shapes across DeepSeek and a non-OpenAI-compatible fixture;
- provider-private fields never appear in observer input;
- deterministic serialization and digest;
- success, tool use, length, abort, retry, and error normalization;
- observer completion precedes provider invocation;
- storage failure prevents the provider mock from being called.

### Pi integration

- the request contains final converted messages, system prompt, active tools,
  selected model, and public options;
- a multi-round tool call commits one request per LLM invocation;
- DeepSeek continuation succeeds without exposing `reasoning_content`;
- response completion before tool execution remains valid.

### Grid-agent trajectory

- every model-request event points to a verified canonical request artifact;
- every provider call has exactly one preceding committed request artifact;
- no public event or API contains raw payloads or hidden reasoning;
- current-run replay reconstructs the exact canonical context;
- legacy runs remain readable and immutable;
- recorder failures retain an honest failed-analysis prefix;
- stdout remains exactly one `question_id`/`answer_output` JSON object.

### Product gates

Run focused suites first, followed by:

```sh
make doctor
make test
make test-e2e
make validate
```

Billable provider validation requires explicit credentials and authorization.

## Acceptance Criteria

1. `make analysis` completes a multi-turn DeepSeek tool-use run without framework
   code recognizing `reasoning_content`.
2. No grid-agent or trajectory source branches on provider-private keys.
3. Every invocation has a complete immutable canonical input committed before I/O.
4. The artifact contains final system prompt, messages, tools, public options,
   provider/model identity, versions, correlations, and digest.
5. Agent, Context, Evidence, and Execution consume only normalized events and
   verified project artifacts.
6. Provider adapters remain exclusively owned by `pi-ai`.
7. Historical runs remain byte-for-byte unchanged and readable.
8. CLI stdout, tool capability, simulator, and evidence contracts remain unchanged.

## References

- `pi-ai` unified API:
  <https://github.com/badlogic/pi-mono/blob/main/packages/ai/README.md>
- `pi-ai` public types:
  <https://github.com/badlogic/pi-mono/blob/main/packages/ai/src/types.ts>
- Vercel AI SDK Core: <https://ai-sdk.dev/docs/ai-sdk-core>
- LiteLLM: <https://docs.litellm.ai/>
- LangChain model/provider interface:
  <https://docs.langchain.com/oss/python/concepts/providers-and-models>
- OpenTelemetry generative-AI conventions:
  <https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/>
