# Provider Request Capture Compatibility Design

## Goal

Make `make analysis` accept Pi provider-request payloads containing JavaScript
`undefined` while preserving the exact JSON request shape needed for native
trajectory replay.

## Decision

The capture hook will validate and persist the payload's JSON transport
representation, not its in-memory JavaScript representation. It will apply the
same semantics as JSON serialization: omit object properties whose value is
`undefined`, and represent `undefined` array elements as `null`.

`NaN`, infinities, `BigInt`, cyclic values, sparse arrays, non-plain objects,
credential fields, and hidden-reasoning fields remain rejected. Those values
cannot be represented as a safe, exact JSON request record.

## Data Flow

`before_provider_request` receives a Pi payload, converts it to its canonical
JSON transport tree, validates the resulting tree, then writes that tree into
the immutable `provider_payload` field of `grid-model-request-input/1.0`.
The analysis runner remains fail-closed only for payloads that have no safe,
faithful JSON representation.

## Acceptance Criteria

1. A payload containing nested object `undefined` values and array
   `undefined` values is captured as the exact JSON transport representation.
2. The captured request remains immutable and contains no credential or hidden
   reasoning field.
3. Existing rejection behavior for non-JSON or unsafe values remains covered.
4. The focused capture and runtime regression suites pass before a billable
   live-provider verification is attempted.
