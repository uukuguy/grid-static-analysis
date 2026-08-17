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
