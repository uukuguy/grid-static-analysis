# Canonical Request Task 1 Report

## RED

Command:

```sh
npm test --prefix packages/pi-grid-tools -- test/model-request-capture.test.mjs
```

Result: failed before implementation.

Key failure:

```text
SyntaxError: The requested module '../src/model-request-capture.mjs' does not provide an export named 'configureModelRequestCapture'
```

## GREEN

Command:

```sh
npm run check --prefix packages/pi-grid-tools
```

Result: passed.

```text
node --check src/domain-tools.mjs && node --check src/model-request-capture.mjs
```

Command:

```sh
npm test --prefix packages/pi-grid-tools
```

Result: passed.

```text
tests 27
pass 27
fail 0
duration_ms 662.100417
```

## Scope

- Added `grid-model-request-input/2.0` JSON Schema.
- Renamed provider-payload capture to canonical model-request capture.
- Registered only `before_model_request` and removed raw provider payload access.
- Added typed semantic projection for model, context, messages, tools, and public options.
- Redacted thinking blocks and omitted opaque text/thinking/tool-call signatures by projection.
- Preserved existing atomic immutable persistence mechanics.

## Review Fix: Closed Typed Options

### RED

Command:

```sh
npm test --prefix packages/pi-grid-tools -- test/model-request-capture.test.mjs
```

Result: failed after adding tests for unknown/malformed public options and typed schema options.

Key failures:

```text
Missing expected rejection.
options.properties.reasoning.enum was undefined
```

### GREEN

Command:

```sh
npm test --prefix packages/pi-grid-tools -- test/model-request-capture.test.mjs
```

Result: passed.

```text
tests 11
pass 11
fail 0
```

Command:

```sh
npm test --prefix packages/pi-grid-tools
```

Result: passed.

```text
tests 29
pass 29
fail 0
```

Command:

```sh
make test
```

Result: passed.

```text
grid-agent: 537 passed
grid-simulator: 87 passed
pi-grid-tools: 29 passed
```
