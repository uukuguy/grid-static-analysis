import test from "node:test";
import assert from "node:assert/strict";
import { access, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { configureTrajectoryCapture } from "../src/trajectory-capture.mjs";

test("captures exact provider payload before the hook returns", async () => {
  const root = await makeTrajectoryFixture();
  const handlers = new Map();
  configureTrajectoryCapture({ on: (name, handler) => handlers.set(name, handler) }, fixturePaths(root));

  const payload = {
    model: "deepseek-v4-flash",
    messages: [{ role: "user", content: "Q7" }],
    tools: [],
  };
  await handlers.get("before_provider_request")({ type: "before_provider_request", payload });

  const requestPath = join(root, "requests/analysis-test-t007-r001/input.json");
  const serialized = await readFile(requestPath, "utf8");
  const request = JSON.parse(serialized);
  assert.equal(request.schema_version, "grid-model-request-input/1.0");
  assert.equal(request.request_id, "analysis-test-t007-r001");
  assert.equal(request.request_index, 1);
  assert.equal(request.turn_id, "analysis-test-t007");
  assert.equal(request.provider, "deepseek");
  assert.equal(request.model, "deepseek-v4-flash");
  assert.match(request.captured_at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
  assert.deepEqual(request.provider_payload, payload);
  assert.deepEqual(request.source_event_sequences, [40, 41]);
  assert.equal(request.context_revision, 59);
  assert.equal(request.context_state_hash, "a".repeat(64));
  assert.equal(serialized.endsWith("\n"), true);
  assert.deepEqual(Object.keys(request), [...Object.keys(request)].sort());
});

test("captures Pi undefined values using JSON transport semantics", async () => {
  const root = await makeTrajectoryFixture();
  const handlers = new Map();
  configureTrajectoryCapture({ on: (name, handler) => handlers.set(name, handler) }, fixturePaths(root));

  await handlers.get("before_provider_request")({
    type: "before_provider_request",
    payload: {
      optional: undefined,
      nested: { omitted: undefined, retained: "yes" },
      messages: [undefined, { content: "Q1", optional: undefined }],
    },
  });

  const request = JSON.parse(
    await readFile(join(root, "requests/analysis-test-t007-r001/input.json"), "utf8"),
  );
  assert.deepEqual(request.provider_payload, {
    nested: { retained: "yes" },
    messages: [null, { content: "Q1" }],
  });
});

test("increments the request index for successive durable captures", async () => {
  const root = await makeTrajectoryFixture();
  const handlers = new Map();
  configureTrajectoryCapture({ on: (name, handler) => handlers.set(name, handler) }, fixturePaths(root));
  const capture = handlers.get("before_provider_request");

  await capture({ type: "before_provider_request", payload: { messages: [] } });
  await capture({ type: "before_provider_request", payload: { messages: [{ role: "user", content: "again" }] } });

  const second = JSON.parse(
    await readFile(join(root, "requests/analysis-test-t007-r002/input.json"), "utf8"),
  );
  assert.equal(second.request_index, 2);
  assert.equal(second.request_id, "analysis-test-t007-r002");
});

test("capture failure invokes fatal exit before returning", async () => {
  const failures = [];
  const handlers = new Map();
  configureTrajectoryCapture(
    { on: (name, handler) => handlers.set(name, handler) },
    { ...fixturePaths(await makeTrajectoryFixture()), requestsPath: "/unwritable/missing" },
    (message) => {
      failures.push(message);
      throw new Error("fatal-86");
    },
  );

  await assert.rejects(
    handlers.get("before_provider_request")({ type: "before_provider_request", payload: {} }),
    /fatal-86/,
  );
  assert.match(failures[0], /trajectory request capture failed/);
});

test("capture rejects an unsafe turn id without writing outside the request root", async () => {
  const root = await makeTrajectoryFixture({ turn_id: "../escape" });
  const failures = [];
  const handlers = new Map();
  configureTrajectoryCapture(
    { on: (name, handler) => handlers.set(name, handler) },
    fixturePaths(root),
    fatalCollector(failures),
  );

  await assert.rejects(
    handlers.get("before_provider_request")({ type: "before_provider_request", payload: {} }),
    /fatal-86/,
  );
  assert.match(failures[0], /unsafe turn_id/);
  await assert.rejects(access(join(root, "escape-r001/input.json")));
});

test("rejects missing or invalid capture state", async () => {
  for (const state of [
    undefined,
    { source_event_sequences: [40, "41"], context_revision: 59, context_state_hash: "a".repeat(64) },
    { source_event_sequences: [40, 41], context_revision: -1, context_state_hash: "a".repeat(64) },
    { source_event_sequences: [40, 41], context_revision: 59, context_state_hash: "not-a-hash" },
  ]) {
    const root = await makeTrajectoryFixture({}, state);
    const failures = [];
    const handlers = new Map();
    configureTrajectoryCapture(
      { on: (name, handler) => handlers.set(name, handler) },
      fixturePaths(root),
      fatalCollector(failures),
    );

    await assert.rejects(
      handlers.get("before_provider_request")({ type: "before_provider_request", payload: {} }),
      /fatal-86/,
    );
    assert.match(failures[0], /trajectory request capture failed/);
  }
});

test("capture rejects non-JSON payload values before creating a request document", async () => {
  for (const payload of [
    { value: Number.NaN },
    { value: 1n },
  ]) {
    const root = await makeTrajectoryFixture();
    const failures = [];
    const handlers = new Map();
    configureTrajectoryCapture(
      { on: (name, handler) => handlers.set(name, handler) },
      fixturePaths(root),
      fatalCollector(failures),
    );

    await assert.rejects(
      handlers.get("before_provider_request")({ type: "before_provider_request", payload }),
      /fatal-86/,
    );
    assert.match(failures[0], /non-JSON provider payload/);
    await assert.rejects(access(join(root, "requests/analysis-test-t007-r001/input.json")));
  }
});

test("capture rejects credential and hidden-reasoning keys before persistence", async () => {
  for (const forbidden of [
    { headers: { Authorization: "Bearer super-secret" } },
    { apiKey: "super-secret" },
    { messages: [{ role: "assistant", hidden_reasoning: "private chain" }] },
    { messages: [{ role: "assistant", reasoning_content: "private chain" }] },
  ]) {
    const root = await makeTrajectoryFixture();
    const failures = [];
    const handlers = new Map();
    configureTrajectoryCapture(
      { on: (name, handler) => handlers.set(name, handler) },
      fixturePaths(root),
      fatalCollector(failures),
    );

    await assert.rejects(
      handlers.get("before_provider_request")({
        type: "before_provider_request",
        payload: forbidden,
      }),
      /fatal-86/,
    );
    assert.match(failures[0], /prohibited provider payload key/);
    await assert.rejects(access(join(root, "requests/analysis-test-t007-r001/input.json")));
  }
});

test("capture refuses to replace an existing request document", async () => {
  const root = await makeTrajectoryFixture();
  const requestPath = join(root, "requests/analysis-test-t007-r001/input.json");
  await mkdir(join(root, "requests/analysis-test-t007-r001"), { recursive: true });
  await writeFile(requestPath, "original\n", "utf8");
  const failures = [];
  const handlers = new Map();
  configureTrajectoryCapture(
    { on: (name, handler) => handlers.set(name, handler) },
    fixturePaths(root),
    fatalCollector(failures),
  );

  await assert.rejects(
    handlers.get("before_provider_request")({ type: "before_provider_request", payload: {} }),
    /fatal-86/,
  );
  assert.match(failures[0], /request path already exists/);
  assert.equal(await readFile(requestPath, "utf8"), "original\n");
});

async function makeTrajectoryFixture(
  activeTurn = { turn_id: "analysis-test-t007", turn_nonce: "nonce-7" },
  captureState = {
    source_event_sequences: [40, 41],
    context_revision: 59,
    context_state_hash: "a".repeat(64),
  },
) {
  const root = await mkdtemp(join(tmpdir(), "grid-trajectory-capture-"));
  await mkdir(join(root, "run/context"), { recursive: true });
  await mkdir(join(root, "requests"), { recursive: true });
  await writeFile(join(root, "run/active-turn.json"), JSON.stringify(activeTurn), "utf8");
  if (captureState !== undefined) {
    await writeFile(
      join(root, "run/context/trajectory-capture-state.json"),
      JSON.stringify(captureState),
      "utf8",
    );
  }
  await writeFile(
    join(root, "run/context/trajectory-allowed-refs.json"),
    JSON.stringify({ refs: [] }),
    "utf8",
  );
  return root;
}

function fixturePaths(root) {
  return {
    requestsPath: join(root, "requests"),
    activeTurnPath: join(root, "run/active-turn.json"),
    captureStatePath: join(root, "run/context/trajectory-capture-state.json"),
    allowedRefsPath: join(root, "run/context/trajectory-allowed-refs.json"),
    providerId: "deepseek",
    modelId: "deepseek-v4-flash",
  };
}

function fatalCollector(failures) {
  return (message) => {
    failures.push(message);
    throw new Error("fatal-86");
  };
}
