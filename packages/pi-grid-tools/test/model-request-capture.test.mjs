import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { access, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { configureModelRequestCapture } from "../src/model-request-capture.mjs";

test("captures a canonical v2 model request from before_model_request only", async () => {
  const root = await makeModelRequestFixture();
  const handlers = new Map();
  configureModelRequestCapture({ on: (name, handler) => handlers.set(name, handler) }, fixturePaths(root));

  assert.equal(handlers.has("before_model_request"), true);
  assert.equal(handlers.has("before_provider_request"), false);

  await handlers.get("before_model_request")(modelRequestEvent());

  const requestPath = join(root, "requests/analysis-test-t007-r001/input.json");
  const serialized = await readFile(requestPath, "utf8");
  const request = JSON.parse(serialized);
  const expectedSemanticRequest = canonicalSemanticFixture();

  assert.equal(serialized, `${JSON.stringify(sortJson(request))}\n`);
  assert.equal(request.schema_version, "grid-model-request-input/2.0");
  assert.equal(request.request_id, "analysis-test-t007-r001");
  assert.equal(request.request_index, 1);
  assert.equal(request.turn_id, "analysis-test-t007");
  assert.match(request.captured_at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
  assert.deepEqual(request.source_event_sequences, [7]);
  assert.equal(request.context_revision, 3);
  assert.equal(request.context_state_hash, "a".repeat(64));
  assert.deepEqual(request.runtime, runtimeIdentity());
  assert.deepEqual(request.semantic_request, expectedSemanticRequest);
  assert.equal(request.semantic_request_sha256, sha256Canonical(expectedSemanticRequest));
  assert.equal(JSON.stringify(request).includes("provider_payload"), false);
  assert.equal(JSON.stringify(request).includes("thinkingSignature"), false);
  assert.equal(JSON.stringify(request).includes("thoughtSignature"), false);
  assert.equal(JSON.stringify(request).includes("textSignature"), false);
  assert.equal(JSON.stringify(request).includes("private chain"), false);
});

test("semantic digest is deterministic across provider identities and changes with model identity", async () => {
  const firstRoot = await makeModelRequestFixture();
  const secondRoot = await makeModelRequestFixture();
  const firstHandlers = new Map();
  const secondHandlers = new Map();
  configureModelRequestCapture({ on: (name, handler) => firstHandlers.set(name, handler) }, fixturePaths(firstRoot));
  configureModelRequestCapture({ on: (name, handler) => secondHandlers.set(name, handler) }, fixturePaths(secondRoot));

  await firstHandlers.get("before_model_request")(modelRequestEvent());
  await secondHandlers.get("before_model_request")(
    modelRequestEvent({ model: { provider: "openrouter", api: "openai-completions", id: "deepseek-v4-flash" } }),
  );

  const first = JSON.parse(await readFile(join(firstRoot, "requests/analysis-test-t007-r001/input.json"), "utf8"));
  const second = JSON.parse(await readFile(join(secondRoot, "requests/analysis-test-t007-r001/input.json"), "utf8"));

  assert.deepEqual(first.semantic_request.context, second.semantic_request.context);
  assert.notEqual(first.semantic_request_sha256, second.semantic_request_sha256);
  assert.equal(first.semantic_request_sha256, sha256Canonical(first.semantic_request));
  assert.equal(second.semantic_request_sha256, sha256Canonical(second.semantic_request));
});

test("increments the request index for successive durable captures", async () => {
  const root = await makeModelRequestFixture();
  const handlers = new Map();
  configureModelRequestCapture({ on: (name, handler) => handlers.set(name, handler) }, fixturePaths(root));
  const capture = handlers.get("before_model_request");

  await capture(modelRequestEvent());
  await capture(modelRequestEvent({ context: { systemPrompt: "next", messages: [], tools: [] } }));

  const second = JSON.parse(
    await readFile(join(root, "requests/analysis-test-t007-r002/input.json"), "utf8"),
  );
  assert.equal(second.request_index, 2);
  assert.equal(second.request_id, "analysis-test-t007-r002");
  assert.equal(second.semantic_request.context.system_prompt, "next");
});

test("capture failure invokes fatal exit before returning", async () => {
  const failures = [];
  const handlers = new Map();
  configureModelRequestCapture(
    { on: (name, handler) => handlers.set(name, handler) },
    { ...fixturePaths(await makeModelRequestFixture()), requestsPath: "/unwritable/missing" },
    fatalCollector(failures),
  );

  await assert.rejects(handlers.get("before_model_request")(modelRequestEvent()), /fatal-86/);
  assert.match(failures[0], /model request capture failed/);
});

test("capture rejects an unsafe turn id without writing outside the request root", async () => {
  const root = await makeModelRequestFixture({ turn_id: "../escape" });
  const failures = [];
  const handlers = new Map();
  configureModelRequestCapture(
    { on: (name, handler) => handlers.set(name, handler) },
    fixturePaths(root),
    fatalCollector(failures),
  );

  await assert.rejects(handlers.get("before_model_request")(modelRequestEvent()), /fatal-86/);
  assert.match(failures[0], /unsafe turn_id/);
  await assert.rejects(access(join(root, "escape-r001/input.json")));
});

test("rejects missing or invalid capture state", async () => {
  for (const state of [
    undefined,
    { source_event_sequences: [7, "8"], context_revision: 3, context_state_hash: "a".repeat(64) },
    { source_event_sequences: [7], context_revision: -1, context_state_hash: "a".repeat(64) },
    { source_event_sequences: [7], context_revision: 3, context_state_hash: "not-a-hash" },
  ]) {
    const root = await makeModelRequestFixture({}, state);
    const failures = [];
    const handlers = new Map();
    configureModelRequestCapture(
      { on: (name, handler) => handlers.set(name, handler) },
      fixturePaths(root),
      fatalCollector(failures),
    );

    await assert.rejects(handlers.get("before_model_request")(modelRequestEvent()), /fatal-86/);
    assert.match(failures[0], /model request capture failed/);
  }
});

test("rejects unknown pi-ai roles and content variants before creating a request document", async () => {
  for (const event of [
    modelRequestEvent({ context: { messages: [{ role: "developer", content: [] }] } }),
    modelRequestEvent({ context: { messages: [{ role: "user", content: [{ type: "audio", data: "x" }] }] } }),
    modelRequestEvent({ context: { tools: [{ name: "tool", description: "bad", parameters: new Date() }] } }),
    modelRequestEvent({ context: { messages: [{ role: "assistant", content: [{ type: "toolCall", id: "call", name: "tool", arguments: { value: 1n } }] }] } }),
  ]) {
    const root = await makeModelRequestFixture();
    const failures = [];
    const handlers = new Map();
    configureModelRequestCapture(
      { on: (name, handler) => handlers.set(name, handler) },
      fixturePaths(root),
      fatalCollector(failures),
    );

    await assert.rejects(handlers.get("before_model_request")(event), /fatal-86/);
    assert.match(failures[0], /canonical model request contract/);
    await assert.rejects(access(join(root, "requests/analysis-test-t007-r001/input.json")));
  }
});

test("capture refuses to replace an existing request document", async () => {
  const root = await makeModelRequestFixture();
  const requestPath = join(root, "requests/analysis-test-t007-r001/input.json");
  await mkdir(join(root, "requests/analysis-test-t007-r001"), { recursive: true });
  await writeFile(requestPath, "original\n", "utf8");
  const failures = [];
  const handlers = new Map();
  configureModelRequestCapture(
    { on: (name, handler) => handlers.set(name, handler) },
    fixturePaths(root),
    fatalCollector(failures),
  );

  await assert.rejects(handlers.get("before_model_request")(modelRequestEvent()), /fatal-86/);
  assert.match(failures[0], /request path already exists/);
  assert.equal(await readFile(requestPath, "utf8"), "original\n");
});

test("schema names the v2 closed canonical contract without provider payload fields", async () => {
  const schema = JSON.parse(
    await readFile(new URL("../../../schemas/grid-model-request-input-v2.schema.json", import.meta.url), "utf8"),
  );
  const schemaText = JSON.stringify(schema);

  assert.equal(schema.$id, "https://grid-static-analysis.local/schemas/grid-model-request-input-v2.schema.json");
  assert.equal(schema.properties.schema_version.const, "grid-model-request-input/2.0");
  assert.equal(schema.additionalProperties, false);
  assert.equal(schemaText.includes("provider_payload"), false);
  assert.equal(schemaText.includes("apiKey"), false);
  assert.equal(schemaText.includes("headers"), false);
  assert.equal(schemaText.includes("onPayload"), false);
  assert.equal(schemaText.includes("onResponse"), false);
});

async function makeModelRequestFixture(
  activeTurn = { turn_id: "analysis-test-t007", turn_nonce: "nonce-7" },
  captureState = {
    source_event_sequences: [7],
    context_revision: 3,
    context_state_hash: "a".repeat(64),
  },
) {
  const root = await mkdtemp(join(tmpdir(), "grid-model-request-capture-"));
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
    runtime: runtimeIdentity(),
  };
}

function runtimeIdentity() {
  return {
    pi_coding_agent_version: "0.80.6",
    pi_ai_version: "0.80.6",
    pi_source_commit: "2b3fda9921b5590f285165287bd442a25817f17b",
    pi_patch_set_sha256: "4".repeat(64),
  };
}

function modelRequestEvent(overrides = {}) {
  return {
    type: "before_model_request",
    model: { provider: "deepseek", api: "openai-completions", id: "deepseek-v4-flash" },
    context: semanticContextFixture(),
    options: {
      reasoning: "medium",
      thinkingBudgets: { medium: 2048 },
      temperature: 0.2,
      maxTokens: 1024,
      transport: "sse",
      cacheRetention: "short",
      timeoutMs: 1234,
      websocketConnectTimeoutMs: 2345,
      maxRetries: 2,
      maxRetryDelayMs: 3000,
      apiKey: "secret-not-public",
      headers: { Authorization: "Bearer secret" },
      onPayload: () => undefined,
    },
    ...overrides,
  };
}

function semanticContextFixture() {
  return {
    systemPrompt: "final system prompt",
    messages: [
      {
        role: "user",
        content: [
          { type: "text", text: "Which lines are overloaded?", textSignature: "opaque-text" },
          { type: "image", data: "data:image/png;base64,abc", mimeType: "image/png" },
        ],
      },
      {
        role: "assistant",
        content: [
          { type: "thinking", thinking: "private chain", thinkingSignature: "opaque-thinking" },
          {
            type: "toolCall",
            id: "call-1",
            name: "grid_topology_branch_endpoints",
            arguments: { context_ref: "context:sha256:" + "b".repeat(64), limit: 2 },
            thoughtSignature: "opaque-tool",
          },
          { type: "text", text: "I will inspect the endpoints." },
        ],
      },
      {
        role: "toolResult",
        toolCallId: "call-1",
        toolName: "grid_topology_branch_endpoints",
        content: [{ type: "text", text: "{\"ok\":true}" }],
        details: { ok: true, result: { branch: "11" }, evidence_refs: ["evidence:sha256:" + "c".repeat(64)] },
        isError: false,
      },
    ],
    tools: [
      {
        name: "grid_topology_branch_endpoints",
        description: "Return branch endpoints.",
        parameters: {
          type: "object",
          additionalProperties: false,
          required: ["context_ref"],
          properties: { context_ref: { type: "string" } },
        },
      },
    ],
  };
}

function canonicalSemanticFixture() {
  return {
    model: { provider: "deepseek", api: "openai-completions", id: "deepseek-v4-flash" },
    context: {
      system_prompt: "final system prompt",
      messages: [
        {
          role: "user",
          content: [
            { type: "text", text: "Which lines are overloaded?" },
            { type: "image", data: "data:image/png;base64,abc", mimeType: "image/png" },
          ],
        },
        {
          role: "assistant",
          content: [
            { type: "thinking", redacted: true },
            {
              type: "toolCall",
              id: "call-1",
              name: "grid_topology_branch_endpoints",
              arguments: { context_ref: "context:sha256:" + "b".repeat(64), limit: 2 },
            },
            { type: "text", text: "I will inspect the endpoints." },
          ],
        },
        {
          role: "toolResult",
          toolCallId: "call-1",
          toolName: "grid_topology_branch_endpoints",
          content: [{ type: "text", text: "{\"ok\":true}" }],
          details: { ok: true, result: { branch: "11" }, evidence_refs: ["evidence:sha256:" + "c".repeat(64)] },
          isError: false,
        },
      ],
      tools: [
        {
          name: "grid_topology_branch_endpoints",
          description: "Return branch endpoints.",
          parameters: {
            type: "object",
            additionalProperties: false,
            required: ["context_ref"],
            properties: { context_ref: { type: "string" } },
          },
        },
      ],
    },
    options: {
      reasoning: "medium",
      thinkingBudgets: { medium: 2048 },
      temperature: 0.2,
      maxTokens: 1024,
      transport: "sse",
      cacheRetention: "short",
      timeoutMs: 1234,
      websocketConnectTimeoutMs: 2345,
      maxRetries: 2,
      maxRetryDelayMs: 3000,
    },
  };
}

function sha256Canonical(value) {
  return createHash("sha256").update(JSON.stringify(sortJson(value)), "utf8").digest("hex");
}

function sortJson(value) {
  if (Array.isArray(value)) {
    return value.map(sortJson);
  }
  if (isPlainObject(value)) {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, sortJson(value[key])]),
    );
  }
  return value;
}

function isPlainObject(value) {
  if (value === null || typeof value !== "object") {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function fatalCollector(failures) {
  return (message) => {
    failures.push(message);
    throw new Error("fatal-86");
  };
}
