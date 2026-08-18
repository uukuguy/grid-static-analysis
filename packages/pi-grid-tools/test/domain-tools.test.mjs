import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, mkdtemp, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import domainToolsExtension, {
  buildGridRequest,
  createGridTool,
  sanitizeEnvironment,
} from "../src/domain-tools.mjs";

test("registers catalog tools and guide without model-owned answer submission", async () => {
  const root = await makeFixtureRoot();
  process.env.GRID_AGENT_TOOL_CATALOG = join(root, "run/tool-catalog.json");
  process.env.GRID_AGENT_GUIDE_INDEX = join(root, "run/guide-index.json");
  process.env.GRID_AGENT_WORKSPACE = join(root, "run");
  await writeCatalog(process.env.GRID_AGENT_TOOL_CATALOG);
  await writeGuideIndex(process.env.GRID_AGENT_GUIDE_INDEX, root);

  const registered = [];
  domainToolsExtension({ registerTool: (tool) => registered.push(tool) });

  assert.equal(
    registered.some((tool) => tool.name === "grid_submit_answer"),
    false,
  );
  assert.deepEqual(
    registered.map((tool) => tool.name).sort(),
    [
      "grid_environment_describe",
      "grid_guide_open",
      "grid_topology_branch_endpoints",
    ],
  );
  const legacyQuery = "grid" + "_query";
  for (const forbidden of ["bash", "read", "write", "edit", legacyQuery]) {
    assert.equal(registered.some((tool) => tool.name === forbidden), false);
  }
  assert.deepEqual(
    registered.find((tool) => tool.name === "grid_topology_branch_endpoints").parameters,
    {
      type: "object",
      additionalProperties: false,
      required: ["context_ref"],
      properties: { context_ref: { type: "string" } },
    },
  );
  assert.equal(
    registered.find((tool) => tool.name === "grid_guide_open")
      .parameters.properties.resource_id.pattern,
    "a^",
  );
});

test("registers newly published static-analysis tools directly from the catalog", async () => {
  const root = await makeFixtureRoot();
  clearOptionalAnalysisEnvironment();
  process.env.GRID_AGENT_TOOL_CATALOG = join(root, "run/tool-catalog.json");
  process.env.GRID_AGENT_GUIDE_INDEX = join(root, "run/guide-index.json");
  process.env.GRID_AGENT_WORKSPACE = join(root, "run");
  const extraTools = [
    ["grid_model_equivalent_derive", "model.equivalent.derive"],
    ["grid_analysis_result_violations_evaluate", "analysis.result.violations.evaluate"],
    ["grid_analysis_result_risk_rank", "analysis.result.risk.rank"],
  ].map(([name, capability]) => ({
    name,
    capability,
    description: `Purpose: ${capability}`,
    input_schema: { type: "object", additionalProperties: false, properties: {} },
  }));
  await writeCatalog(process.env.GRID_AGENT_TOOL_CATALOG, extraTools);
  await writeGuideIndex(process.env.GRID_AGENT_GUIDE_INDEX, root);

  const registered = [];
  domainToolsExtension({ registerTool: (tool) => registered.push(tool) });

  for (const [name] of extraTools.map((tool) => [tool.name])) {
    assert.equal(registered.some((tool) => tool.name === name), true);
  }
});

test("analysis tools expose bounded context without model-owned answer submission", async () => {
  const root = await makeFixtureRoot();
  await configureAnalysisPaths(
    root,
    {
      turn_id: "analysis-test-t002",
      turn_nonce: "nonce-2",
    },
    { schema_version: "analysis-context-view/1.0", revision: 9, state_hash: "sha256:test" },
  );

  const registered = [];
  domainToolsExtension({ registerTool: (tool) => registered.push(tool) });

  assert.equal(registered.some((tool) => tool.name === "grid_analysis_context_get"), true);
  assert.equal(registered.some((tool) => tool.name === "grid_submit_answer"), false);
  const context = await registered.find((tool) => tool.name === "grid_analysis_context_get").execute("context-1", {});

  assert.equal(context.isError, undefined);
  assert.equal(context.details.result.revision, 9);
});

test("analysis context tool is optional for legacy single-run launches", async () => {
  const root = await makeFixtureRoot();
  process.env.GRID_AGENT_TOOL_CATALOG = join(root, "run/tool-catalog.json");
  process.env.GRID_AGENT_GUIDE_INDEX = join(root, "run/guide-index.json");
  process.env.GRID_AGENT_WORKSPACE = join(root, "run");
  delete process.env.GRID_AGENT_ACTIVE_TURN;
  delete process.env.GRID_AGENT_ANALYSIS_CONTEXT_VIEW;
  await writeCatalog(process.env.GRID_AGENT_TOOL_CATALOG);
  await writeGuideIndex(process.env.GRID_AGENT_GUIDE_INDEX, root);

  const registered = [];
  domainToolsExtension({ registerTool: (tool) => registered.push(tool) });

  assert.equal(registered.some((tool) => tool.name === "grid_analysis_context_get"), false);
  assert.equal(registered.some((tool) => tool.name === "grid_submit_answer"), false);
});

test("startup accepts future writable active-turn file inside workspace", async () => {
  const root = await makeFixtureRoot();
  clearOptionalAnalysisEnvironment();
  process.env.GRID_AGENT_TOOL_CATALOG = join(root, "run/tool-catalog.json");
  process.env.GRID_AGENT_GUIDE_INDEX = join(root, "run/guide-index.json");
  process.env.GRID_AGENT_WORKSPACE = join(root, "run");
  process.env.GRID_AGENT_ACTIVE_TURN = join(root, "run/active-turn.json");
  await writeCatalog(process.env.GRID_AGENT_TOOL_CATALOG);
  await writeGuideIndex(process.env.GRID_AGENT_GUIDE_INDEX, root);

  const registered = [];
  domainToolsExtension({ registerTool: (tool) => registered.push(tool) });

  assert.equal(registered.some((tool) => tool.name === "grid_record_decision"), false);
});

test("records bounded decisions only against controller-known refs", async () => {
  const { registered, root } = await configuredNativeTools();
  const known = "result:sha256:" + "a".repeat(64);
  await writeFile(
    join(root, "run/context/trajectory-allowed-refs.json"),
    JSON.stringify({ refs: [known] }),
    "utf8",
  );
  const decision = registered.find((tool) => tool.name === "grid_record_decision");

  const accepted = await decision.execute("decision-1", {
    intent: "Assess line 17 N-1 security",
    decision: "Run the published contingency capability",
    next_action: "Resolve line 17 and execute N-1",
    refs: [known],
  });
  const rejected = await decision.execute("decision-2", {
    intent: "Assess",
    decision: "Guess",
    next_action: "Answer",
    refs: ["result:sha256:" + "b".repeat(64)],
  });
  const outOfBounds = await decision.execute("decision-3", {
    intent: "x".repeat(501),
    decision: "Guess",
    next_action: "Answer",
    refs: [],
  });

  assert.equal(accepted.isError, undefined);
  assert.equal(accepted.details.capability, "grid_record_decision");
  assert.deepEqual(accepted.details.result.refs, [known]);
  assert.equal(rejected.isError, true);
  assert.equal(rejected.details.error.code, "unknown_decision_ref");
  assert.equal(outOfBounds.isError, true);
  assert.equal(outOfBounds.details.error.code, "invalid_decision");
});

test("native request capture subscribes to before_model_request only", async () => {
  const root = await makeFixtureRoot();
  await configureAnalysisPaths(
    root,
    { turn_id: "analysis-test-t002", turn_nonce: "nonce-2" },
    { schema_version: "analysis-context-view/1.0", revision: 9, state_hash: "sha256:test" },
  );
  process.env.GRID_AGENT_TRAJECTORY_REQUESTS = join(root, "run/requests");
  process.env.GRID_AGENT_TRAJECTORY_CAPTURE_STATE = join(
    root,
    "run/context/trajectory-capture-state.json",
  );
  process.env.GRID_AGENT_TRAJECTORY_ALLOWED_REFS = join(
    root,
    "run/context/trajectory-allowed-refs.json",
  );
  process.env.GRID_AGENT_TRAJECTORY_ACKS = join(root, ".grid-agent/trajectory-acks/analysis-test");
  await mkdir(process.env.GRID_AGENT_TRAJECTORY_REQUESTS, { recursive: true });
  await mkdir(process.env.GRID_AGENT_TRAJECTORY_ACKS, { recursive: true });
  await writeFile(
    process.env.GRID_AGENT_TRAJECTORY_CAPTURE_STATE,
    JSON.stringify({
      source_event_sequences: [1],
      context_revision: 1,
      context_state_hash: "a".repeat(64),
    }),
    "utf8",
  );
  await writeFile(
    process.env.GRID_AGENT_TRAJECTORY_ALLOWED_REFS,
    JSON.stringify({ refs: [] }),
    "utf8",
  );
  const handlers = new Map();

  domainToolsExtension({
    on: (name, handler) => handlers.set(name, handler),
    registerTool: () => undefined,
  });

  assert.equal(handlers.has("before_model_request"), true);
  assert.equal(handlers.has("before_provider_request"), false);
});

test("removes provider credentials from gridctl child environment", () => {
  const clean = sanitizeEnvironment(
    {
      PATH: "/safe/bin",
      OPENAI_API_KEY: "openai-secret",
      CUSTOM_PROVIDER_TOKEN: "custom-secret",
      GRID_AGENT_SECRET_ENV_NAMES: "CUSTOM_PROVIDER_TOKEN",
    },
    ["OPENAI_API_KEY", "CUSTOM_PROVIDER_TOKEN"],
  );

  assert.deepEqual(clean, { PATH: "/safe/bin" });
});

test("builds capability protocol requests with correlation ids", () => {
  assert.deepEqual(buildGridRequest("model.element.get", { identifier: "11" }, "req-1"), {
    protocol: "grid-capability",
    protocol_version: "1.0",
    request_id: "req-1",
    capability: "model.element.get",
    arguments: { identifier: "11" },
  });
});

test("maps typed gridctl errors to tool errors", async () => {
  const tool = createGridTool(
    {
      name: "grid_context_open",
      capability: "context.open",
      description: "Open context",
      input_schema: { type: "object", additionalProperties: false, properties: {} },
    },
    async (payload) => ({
      protocol: "grid-capability",
      protocol_version: "1.0",
      request_id: payload.request_id,
      ok: false,
      error: { code: "model_not_found", phase: "resolve", message: "missing model" },
    }),
  );

  const result = await tool.execute("call-1", {});

  assert.equal(result.isError, true);
  assert.deepEqual(result.details.error, {
    code: "model_not_found",
    phase: "resolve",
    message: "missing model",
  });
});

test("returns canonical typed tool-result details for successful gridctl calls", async () => {
  const evidenceRef = "evidence:sha256:" + "a".repeat(64);
  const tool = createGridTool(
    {
      name: "grid_topology_branch_endpoints",
      capability: "topology.branch.endpoints.get",
      description: "Endpoints",
      input_schema: { type: "object", additionalProperties: false, properties: {} },
    },
    async (payload) => ({
      protocol: "grid-capability",
      protocol_version: "1.0",
      request_id: payload.request_id,
      ok: true,
      result: {
        branch: { identifier: "11" },
        evidence_ref: evidenceRef,
      },
    }),
  );

  const result = await tool.execute("call-1", {});

  assert.equal(result.isError, undefined);
  assert.deepEqual(result.details, {
    event: "tool_result",
    capability: "topology.branch.endpoints.get",
    ok: true,
    result: {
      branch: { identifier: "11" },
      evidence_ref: evidenceRef,
    },
    evidence_refs: [evidenceRef],
  });
});

test("rejects mismatched gridctl response correlation", async () => {
  const tool = createGridTool(
    {
      name: "grid_context_open",
      capability: "context.open",
      description: "Open context",
      input_schema: { type: "object", additionalProperties: false, properties: {} },
    },
    async () => ({
      protocol: "grid-capability",
      protocol_version: "1.0",
      request_id: "wrong-request",
      ok: true,
      result: {},
    }),
  );

  const result = await tool.execute("call-1", {});

  assert.equal(result.isError, true);
  assert.equal(result.details.error.code, "response_correlation_mismatch");
});

test("guide tool rejects traversal and opens published guides", async () => {
  const root = await makeFixtureRoot();
  clearOptionalAnalysisEnvironment();
  const guidePath = join(root, "guides/topology.md");
  const registered = [];
  process.env.GRID_AGENT_TOOL_CATALOG = join(root, "run/tool-catalog.json");
  process.env.GRID_AGENT_GUIDE_INDEX = join(root, "run/guide-index.json");
  process.env.GRID_AGENT_WORKSPACE = join(root, "run");
  await writeCatalog(process.env.GRID_AGENT_TOOL_CATALOG);
  await writeFile(guidePath, "# Topology\n\nUse endpoint capability.\n", "utf8");
  await writeGuideIndex(process.env.GRID_AGENT_GUIDE_INDEX, root, {
    topology: guidePath,
    escape: join(root, "../outside.md"),
  });

  domainToolsExtension({ registerTool: (tool) => registered.push(tool) });
  const guide = registered.find((tool) => tool.name === "grid_guide_open");

  assert.deepEqual(
    guide.parameters.properties.resource_id.enum,
    ["escape", "topology"],
  );
  assert.match(guide.description, /escape, topology/);

  const opened = await guide.execute("guide-1", { resource_id: "topology" });
  const rejected = await guide.execute("guide-2", { resource_id: "../outside" });
  const escaped = await guide.execute("guide-3", { resource_id: "escape" });

  assert.equal(opened.isError, undefined);
  assert.match(opened.details.result.text, /endpoint capability/);
  assert.equal(rejected.isError, true);
  assert.equal(escaped.isError, true);
});

test("guide tool rejects lexically allowed symlinks outside the published root", async () => {
  const root = await makeFixtureRoot();
  clearOptionalAnalysisEnvironment();
  const outside = await mkdtemp(join(tmpdir(), "grid-domain-tools-outside-"));
  const outsideGuidePath = join(outside, "secret.md");
  const guideSymlinkPath = join(root, "guides/escape.md");
  const registered = [];
  process.env.GRID_AGENT_TOOL_CATALOG = join(root, "run/tool-catalog.json");
  process.env.GRID_AGENT_GUIDE_INDEX = join(root, "run/guide-index.json");
  process.env.GRID_AGENT_WORKSPACE = join(root, "run");
  await writeCatalog(process.env.GRID_AGENT_TOOL_CATALOG);
  await writeFile(outsideGuidePath, "outside guide secret", "utf8");
  await symlink(outsideGuidePath, guideSymlinkPath);
  await writeGuideIndex(process.env.GRID_AGENT_GUIDE_INDEX, root, {
    escape: guideSymlinkPath,
  });

  domainToolsExtension({ registerTool: (tool) => registered.push(tool) });
  const guide = registered.find((tool) => tool.name === "grid_guide_open");

  const result = await guide.execute("guide-escape", { resource_id: "escape" });

  assert.equal(result.isError, true);
  assert.equal(result.details.error.code, "guide_path_rejected");
  assert.doesNotMatch(result.content[0].text, /outside guide secret/);
});

test("startup rejects configured symlink paths that escape the workspace", async () => {
  const cases = [
    {
      name: "GRID_AGENT_TOOL_CATALOG",
      link: "tool-catalog-link.json",
      outside: "tool-catalog.json",
      writeOutside: writeCatalog,
    },
    {
      name: "GRID_AGENT_GUIDE_INDEX",
      link: "guide-index-link.json",
      outside: "guide-index.json",
      writeOutside: async (path, root) => writeGuideIndex(path, root),
    },
    {
      name: "GRID_AGENT_ACTIVE_TURN",
      link: "active-turn.json",
      outside: "active-turn.json",
      writeOutside: async (path) => writeFile(path, JSON.stringify({ turn_id: "x", turn_nonce: "n" }), "utf8"),
    },
  ];

  for (const testCase of cases) {
    const root = await makeFixtureRoot();
    const outside = await mkdtemp(join(tmpdir(), "grid-domain-tools-outside-"));
    const outsidePath = join(outside, testCase.outside);
    const linkPath = join(root, "run", testCase.link);
    const registered = [];
    await testCase.writeOutside(outsidePath, root);
    await symlink(outsidePath, linkPath);
    process.env.GRID_AGENT_TOOL_CATALOG = join(root, "run/tool-catalog.json");
    process.env.GRID_AGENT_GUIDE_INDEX = join(root, "run/guide-index.json");
    process.env.GRID_AGENT_WORKSPACE = join(root, "run");
    await writeCatalog(process.env.GRID_AGENT_TOOL_CATALOG);
    await writeGuideIndex(process.env.GRID_AGENT_GUIDE_INDEX, root);
    process.env[testCase.name] = linkPath;

    assert.throws(
      () => domainToolsExtension({ registerTool: (tool) => registered.push(tool) }),
      new RegExp(`${testCase.name}.*outside GRID_AGENT_WORKSPACE`),
    );
    assert.deepEqual(registered, []);
  }
});

async function makeFixtureRoot() {
  const root = await mkdtemp(join(tmpdir(), "grid-domain-tools-"));
  await mkdir(join(root, "run"), { recursive: true });
  await mkdir(join(root, "guides"), { recursive: true });
  return root;
}

async function configureAnalysisPaths(root, activeTurn, contextView) {
  clearNativeEnvironment();
  process.env.GRID_AGENT_TOOL_CATALOG = join(root, "run/tool-catalog.json");
  process.env.GRID_AGENT_GUIDE_INDEX = join(root, "run/guide-index.json");
  process.env.GRID_AGENT_WORKSPACE = join(root, "run");
  process.env.GRID_AGENT_ACTIVE_TURN = join(root, "run/active-turn.json");
  process.env.GRID_AGENT_ANALYSIS_CONTEXT_VIEW = join(root, "run/context/analysis-context-view.json");
  await mkdir(join(root, "run/context"), { recursive: true });
  await writeCatalog(process.env.GRID_AGENT_TOOL_CATALOG);
  await writeGuideIndex(process.env.GRID_AGENT_GUIDE_INDEX, root);
  await writeFile(process.env.GRID_AGENT_ACTIVE_TURN, JSON.stringify(activeTurn), "utf8");
  await writeFile(process.env.GRID_AGENT_ANALYSIS_CONTEXT_VIEW, JSON.stringify(contextView), "utf8");
}

function clearNativeEnvironment() {
  for (const name of [
    "GRID_AGENT_TRAJECTORY_REQUESTS",
    "GRID_AGENT_TRAJECTORY_CAPTURE_STATE",
    "GRID_AGENT_TRAJECTORY_ALLOWED_REFS",
    "GRID_AGENT_TRAJECTORY_ACKS",
  ]) {
    delete process.env[name];
  }
}

function clearOptionalAnalysisEnvironment() {
  clearNativeEnvironment();
  delete process.env.GRID_AGENT_ACTIVE_TURN;
  delete process.env.GRID_AGENT_ANALYSIS_CONTEXT_VIEW;
}

async function configuredNativeTools() {
  const root = await makeFixtureRoot();
  await configureAnalysisPaths(
    root,
    { turn_id: "analysis-test-t002", turn_nonce: "nonce-2" },
    { schema_version: "analysis-context-view/1.0", revision: 9, state_hash: "sha256:test" },
  );
  process.env.GRID_AGENT_TRAJECTORY_REQUESTS = join(root, "run/requests");
  process.env.GRID_AGENT_TRAJECTORY_CAPTURE_STATE = join(
    root,
    "run/context/trajectory-capture-state.json",
  );
  process.env.GRID_AGENT_TRAJECTORY_ALLOWED_REFS = join(
    root,
    "run/context/trajectory-allowed-refs.json",
  );
  process.env.GRID_AGENT_TRAJECTORY_ACKS = join(root, ".grid-agent/trajectory-acks/analysis-test");
  await mkdir(process.env.GRID_AGENT_TRAJECTORY_REQUESTS, { recursive: true });
  await mkdir(process.env.GRID_AGENT_TRAJECTORY_ACKS, { recursive: true });
  await writeFile(
    process.env.GRID_AGENT_TRAJECTORY_CAPTURE_STATE,
    JSON.stringify({
      source_event_sequences: [1],
      context_revision: 1,
      context_state_hash: "a".repeat(64),
    }),
    "utf8",
  );
  await writeFile(
    process.env.GRID_AGENT_TRAJECTORY_ALLOWED_REFS,
    JSON.stringify({ refs: [] }),
    "utf8",
  );
  const registered = [];
  domainToolsExtension({
    on: () => undefined,
    registerTool: (tool) => registered.push(tool),
  });
  return { registered, root };
}

async function writeCatalog(path, extraTools = []) {
  await writeFile(
    path,
    JSON.stringify({
      protocol: "grid-tool-catalog",
      version: "1.0",
      fingerprint: "sha256:test",
      tools: [
        {
          name: "grid_environment_describe",
          capability: "environment.describe",
          description: "Purpose: describe environment",
          input_schema: { type: "object", additionalProperties: false, properties: {} },
        },
        {
          name: "grid_topology_branch_endpoints",
          capability: "topology.branch.endpoints.get",
          description: "Purpose: endpoints",
          input_schema: {
            type: "object",
            additionalProperties: false,
            required: ["context_ref"],
            properties: { context_ref: { type: "string" } },
          },
        },
        ...extraTools,
      ],
    }),
    "utf8",
  );
}

async function writeGuideIndex(path, root, resources = {}) {
  await writeFile(
    path,
    JSON.stringify({
      protocol: "grid-guide-index",
      version: "1.0",
      root: join(root, "guides"),
      resources,
    }),
    "utf8",
  );
}
