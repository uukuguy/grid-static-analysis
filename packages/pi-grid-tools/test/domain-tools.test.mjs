import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import domainToolsExtension, {
  buildGridRequest,
  createGridTool,
  sanitizeEnvironment,
} from "../src/domain-tools.mjs";

test("registers catalog tools, guide, and answer submission only", async () => {
  const root = await makeFixtureRoot();
  process.env.GRID_AGENT_TOOL_CATALOG = join(root, "run/tool-catalog.json");
  process.env.GRID_AGENT_GUIDE_INDEX = join(root, "run/guide-index.json");
  process.env.GRID_AGENT_WORKSPACE = join(root, "run");
  process.env.GRID_AGENT_ANSWER_DRAFT = join(root, "run/answer-draft.json");
  await writeCatalog(process.env.GRID_AGENT_TOOL_CATALOG);
  await writeGuideIndex(process.env.GRID_AGENT_GUIDE_INDEX, root);

  const registered = [];
  domainToolsExtension({ registerTool: (tool) => registered.push(tool) });

  assert.deepEqual(
    registered.map((tool) => tool.name).sort(),
    [
      "grid_environment_describe",
      "grid_guide_open",
      "grid_submit_answer",
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
});

test("analysis tools expose bounded context and bind answer to active turn", async () => {
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
  const context = await registered.find((tool) => tool.name === "grid_analysis_context_get").execute("context-1", {});
  const submitted = await registered.find((tool) => tool.name === "grid_submit_answer").execute("submit-1", {
    answer_output: "答案",
    result_refs: [],
    claim_evidence_refs: [],
  });

  assert.equal(context.isError, undefined);
  assert.equal(context.details.result.revision, 9);
  assert.deepEqual(JSON.parse(await readFile(process.env.GRID_AGENT_ANSWER_DRAFT, "utf8")), {
    turn_id: "analysis-test-t002",
    turn_nonce: "nonce-2",
    answer_output: "答案",
    result_refs: [],
    claim_evidence_refs: [],
  });
  assert.equal(submitted.details.result.turn_id, "analysis-test-t002");
  assert.equal(submitted.details.result.turn_nonce, "nonce-2");
});

test("analysis context tool is optional for legacy single-run launches", async () => {
  const root = await makeFixtureRoot();
  process.env.GRID_AGENT_TOOL_CATALOG = join(root, "run/tool-catalog.json");
  process.env.GRID_AGENT_GUIDE_INDEX = join(root, "run/guide-index.json");
  process.env.GRID_AGENT_WORKSPACE = join(root, "run");
  process.env.GRID_AGENT_ANSWER_DRAFT = join(root, "run/answer-draft.json");
  delete process.env.GRID_AGENT_ACTIVE_TURN;
  delete process.env.GRID_AGENT_ANALYSIS_CONTEXT_VIEW;
  await writeCatalog(process.env.GRID_AGENT_TOOL_CATALOG);
  await writeGuideIndex(process.env.GRID_AGENT_GUIDE_INDEX, root);

  const registered = [];
  domainToolsExtension({ registerTool: (tool) => registered.push(tool) });

  assert.equal(registered.some((tool) => tool.name === "grid_analysis_context_get"), false);
  const submit = registered.find((tool) => tool.name === "grid_submit_answer");
  await submit.execute("submit-legacy", {
    answer_output: "legacy",
    result_refs: [],
    claim_evidence_refs: [],
  });
  assert.deepEqual(JSON.parse(await readFile(process.env.GRID_AGENT_ANSWER_DRAFT, "utf8")), {
    answer_output: "legacy",
    result_refs: [],
    claim_evidence_refs: [],
  });
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
  const guidePath = join(root, "guides/topology.md");
  const registered = [];
  process.env.GRID_AGENT_TOOL_CATALOG = join(root, "run/tool-catalog.json");
  process.env.GRID_AGENT_GUIDE_INDEX = join(root, "run/guide-index.json");
  process.env.GRID_AGENT_WORKSPACE = join(root, "run");
  process.env.GRID_AGENT_ANSWER_DRAFT = join(root, "run/answer-draft.json");
  await writeCatalog(process.env.GRID_AGENT_TOOL_CATALOG);
  await writeFile(guidePath, "# Topology\n\nUse endpoint capability.\n", "utf8");
  await writeGuideIndex(process.env.GRID_AGENT_GUIDE_INDEX, root, {
    topology: guidePath,
    escape: join(root, "../outside.md"),
  });

  domainToolsExtension({ registerTool: (tool) => registered.push(tool) });
  const guide = registered.find((tool) => tool.name === "grid_guide_open");

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
  const outside = await mkdtemp(join(tmpdir(), "grid-domain-tools-outside-"));
  const outsideGuidePath = join(outside, "secret.md");
  const guideSymlinkPath = join(root, "guides/escape.md");
  const registered = [];
  process.env.GRID_AGENT_TOOL_CATALOG = join(root, "run/tool-catalog.json");
  process.env.GRID_AGENT_GUIDE_INDEX = join(root, "run/guide-index.json");
  process.env.GRID_AGENT_WORKSPACE = join(root, "run");
  process.env.GRID_AGENT_ANSWER_DRAFT = join(root, "run/answer-draft.json");
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
      name: "GRID_AGENT_ANSWER_DRAFT",
      link: "answer-draft.json",
      outside: "answer-draft.json",
      writeOutside: async (path) => writeFile(path, "{}", "utf8"),
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
    process.env.GRID_AGENT_ANSWER_DRAFT = join(root, "run/answer-draft.json");
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

test("answer submission atomically writes the configured draft path", async () => {
  const root = await makeFixtureRoot();
  const draftPath = join(root, "run/answer-draft.json");
  const registered = [];
  process.env.GRID_AGENT_TOOL_CATALOG = join(root, "run/tool-catalog.json");
  process.env.GRID_AGENT_GUIDE_INDEX = join(root, "run/guide-index.json");
  process.env.GRID_AGENT_WORKSPACE = join(root, "run");
  process.env.GRID_AGENT_ANSWER_DRAFT = draftPath;
  await writeCatalog(process.env.GRID_AGENT_TOOL_CATALOG);
  await writeGuideIndex(process.env.GRID_AGENT_GUIDE_INDEX, root);

  domainToolsExtension({ registerTool: (tool) => registered.push(tool) });
  const submit = registered.find((tool) => tool.name === "grid_submit_answer");
  const result = await submit.execute("submit-1", {
    answer_output: "线路11连接母线6与母线11。",
    result_refs: [],
    claim_evidence_refs: ["evidence:sha256:" + "a".repeat(64)],
  });

  assert.equal(result.isError, undefined);
  assert.deepEqual(JSON.parse(await readFile(draftPath, "utf8")), {
    answer_output: "线路11连接母线6与母线11。",
    result_refs: [],
    claim_evidence_refs: ["evidence:sha256:" + "a".repeat(64)],
  });
});

test("answer submission atomically writes declared result refs", async () => {
  const root = await makeFixtureRoot();
  const draftPath = join(root, "run/answer-draft.json");
  const registered = [];
  process.env.GRID_AGENT_TOOL_CATALOG = join(root, "run/tool-catalog.json");
  process.env.GRID_AGENT_GUIDE_INDEX = join(root, "run/guide-index.json");
  process.env.GRID_AGENT_WORKSPACE = join(root, "run");
  process.env.GRID_AGENT_ANSWER_DRAFT = draftPath;
  await writeCatalog(process.env.GRID_AGENT_TOOL_CATALOG);
  await writeGuideIndex(process.env.GRID_AGENT_GUIDE_INDEX, root);

  domainToolsExtension({ registerTool: (tool) => registered.push(tool) });
  const submit = registered.find((tool) => tool.name === "grid_submit_answer");
  const resultRef = "result:sha256:" + "b".repeat(64);
  const result = await submit.execute("submit-result-refs", {
    answer_output: "交流潮流已收敛。",
    result_refs: [resultRef],
    claim_evidence_refs: ["evidence:sha256:" + "a".repeat(64)],
  });

  assert.equal(result.isError, undefined);
  assert.deepEqual(JSON.parse(await readFile(draftPath, "utf8")), {
    answer_output: "交流潮流已收敛。",
    result_refs: [resultRef],
    claim_evidence_refs: ["evidence:sha256:" + "a".repeat(64)],
  });
});

async function makeFixtureRoot() {
  const root = await mkdtemp(join(tmpdir(), "grid-domain-tools-"));
  await mkdir(join(root, "run"), { recursive: true });
  await mkdir(join(root, "guides"), { recursive: true });
  return root;
}

async function configureAnalysisPaths(root, activeTurn, contextView) {
  process.env.GRID_AGENT_TOOL_CATALOG = join(root, "run/tool-catalog.json");
  process.env.GRID_AGENT_GUIDE_INDEX = join(root, "run/guide-index.json");
  process.env.GRID_AGENT_WORKSPACE = join(root, "run");
  process.env.GRID_AGENT_ANSWER_DRAFT = join(root, "run/answer-draft.json");
  process.env.GRID_AGENT_ACTIVE_TURN = join(root, "run/active-turn.json");
  process.env.GRID_AGENT_ANALYSIS_CONTEXT_VIEW = join(root, "run/context/analysis-context-view.json");
  await mkdir(join(root, "run/context"), { recursive: true });
  await writeCatalog(process.env.GRID_AGENT_TOOL_CATALOG);
  await writeGuideIndex(process.env.GRID_AGENT_GUIDE_INDEX, root);
  await writeFile(process.env.GRID_AGENT_ACTIVE_TURN, JSON.stringify(activeTurn), "utf8");
  await writeFile(process.env.GRID_AGENT_ANALYSIS_CONTEXT_VIEW, JSON.stringify(contextView), "utf8");
}

async function writeCatalog(path) {
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
