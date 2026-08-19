# OpenAI Responses Tool Call ID Normalization Design

## Problem

Pi represents an OpenAI Responses function call as a compound identifier such
as `call_...|fc_...`, combining the API `call_id` and response item ID. This is
valid Pi behavior and is required when Pi sends later function-call output back
to a Responses provider.

`grid-agent` currently copies that provider-facing identifier into its semantic
trajectory. Native capture then uses the identifier in an immutable tool-result
artifact path. Artifact identities deliberately allow only
`[A-Za-z0-9._:-]`, so the compound identifier is rejected before the tool can
complete with `ArtifactIntegrityError: artifact identity is invalid`.

The failure affects the OpenAI Responses protocol shape rather than a specific
local model. The provider request, model reasoning, and tool selection can all
succeed before capture aborts the turn.

## Goals

- Accept Pi tool events produced by OpenAI Responses providers.
- Keep semantic tool-start and tool-result events correlated by one stable ID.
- Preserve the artifact registry's portable, traversal-resistant identity
  alphabet.
- Preserve the original provider/Pi identifier for forensic inspection.
- Leave already-safe tool call IDs unchanged.

## Non-goals

- Changing Pi's provider-facing tool call identifier or Responses message
  replay.
- Expanding the artifact filename alphabet to include provider-defined
  punctuation.
- Rewriting historical run files.
- Changing tool arguments, tool results, evidence, or answer submission.

## Design

The RPC adapter is the trust boundary between raw Pi events and project-owned
semantic events. `_event_tool_call_id()` will return a project-safe semantic ID:

- a non-empty ID that already matches the artifact identity pattern and length
  limit is returned unchanged;
- any other non-empty ID is mapped deterministically to
  `pi-call-<64 lowercase SHA-256 hex characters>`.

The same function is used for tool-start and tool-result events, so both sides
of a call receive the same semantic ID and pending-call correlation continues
to work. Hashing the complete raw value avoids collisions introduced by simple
character replacement or truncation.

The raw Pi session under `runs/<run-id>/pi/*.jsonl` remains unchanged and keeps
the compound identifier. Project semantic events, scopes, filenames, report
links, and trajectory projections use only the normalized ID.

Normalization occurs in `runtime/rpc.py`, before native capture and context
projection. The artifact registry stays strict and requires no provider-aware
logic.

## Failure Behavior

A missing or empty tool call ID remains missing and is rejected by existing
capture validation. Normalization changes only syntactically unsafe, non-empty
IDs. It does not hide malformed tool events or relax start/result pairing.

## Verification

Tests will prove that:

- a normal `call-1` ID remains `call-1`;
- `call_...|fc_...` receives a stable safe ID;
- start and result events receive the same normalized ID;
- native capture writes and verifies the corresponding tool artifact;
- different unsafe raw IDs do not receive the same semantic ID;
- the existing runtime and complete grid-agent suites remain green.

A live local-provider question that requires `grid_model_list` and subsequent
grid tools must progress beyond the first tool start without artifact identity
failure.
