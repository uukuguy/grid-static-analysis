import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import packageJson from "../package.json" with { type: "json" };
import domainToolsExtension from "../src/domain-tools.mjs";
import { DefaultResourceLoader } from "@earendil-works/pi-coding-agent";

const ROOT = resolve(fileURLToPath(new URL("../../..", import.meta.url)));

test("package pins the validated Pi API", () => {
  assert.equal(packageJson.dependencies["@earendil-works/pi-coding-agent"], "0.80.6");
});

test("package surface admits canonical request hook without expanding grid tools", async () => {
  const tempDir = await mkdtemp(join(tmpdir(), "grid-pi-package-surface-"));
  const originalEnv = { ...process.env };
  try {
    const cwd = join(tempDir, "project");
    const agentDir = join(tempDir, "agent");
    const workspace = join(tempDir, "workspace");
    const extensionPath = join(tempDir, "canonical-request-extension.mjs");
    const catalogPath = join(workspace, "tool-catalog.json");
    const guideRoot = join(workspace, "guides");
    const guidePath = join(guideRoot, "topology.md");
    const guideIndexPath = join(workspace, "guide-index.json");

    await mkdir(cwd, { recursive: true });
    await mkdir(agentDir, { recursive: true });
    await mkdir(guideRoot, { recursive: true });
    await writeFile(
      extensionPath,
      "export default function canonicalRequestProbe(pi) {\n" +
        "  pi.on('before_model_request', () => undefined);\n" +
        "}\n",
      "utf8",
    );
    await writeFile(guidePath, "topology guide\n", "utf8");
    await writeFile(
      catalogPath,
      JSON.stringify({
        tools: [
          gridToolContract("grid_model_list", "context.models.list"),
          gridToolContract("topology_branch_endpoints_get", "topology.branch.endpoints.get"),
          gridToolContract("grid_record_decision", "grid_record_decision"),
        ],
      }),
      "utf8",
    );
    await writeFile(
      guideIndexPath,
      JSON.stringify({ root: guideRoot, resources: { topology: guidePath } }),
      "utf8",
    );

    const loader = new DefaultResourceLoader({
      cwd,
      agentDir,
      additionalExtensionPaths: [extensionPath],
    });
    await loader.reload();
    const extensions = loader.getExtensions();
    assert.deepEqual(extensions.errors, []);
    assert.equal(extensions.extensions.length, 1);
    assert.equal(extensions.extensions[0].handlers.get("before_model_request")?.length, 1);

    const patchText = await readPatchText();
    assert.match(patchText, /on\(event: "before_model_request"/);
    assert.match(patchText, /emitBeforeModelRequest/);
    assert.doesNotMatch(patchText, /\breasoning_content\b/);

    Object.assign(process.env, {
      GRID_AGENT_WORKSPACE: workspace,
      GRID_AGENT_TOOL_CATALOG: catalogPath,
      GRID_AGENT_GUIDE_INDEX: guideIndexPath,
    });
    const registeredTools = [];
    domainToolsExtension({
      on() {},
      registerTool(tool) {
        registeredTools.push(tool.name);
      },
    });

    assert.deepEqual(registeredTools, [
      "grid_model_list",
      "topology_branch_endpoints_get",
      "grid_guide_open",
    ]);
    const legacyQuery = "grid" + "_query";
    assert(!registeredTools.some((name) => ["read", "bash", "shell", legacyQuery].includes(name)));
  } finally {
    process.env = originalEnv;
    await rm(tempDir, { recursive: true, force: true });
  }
});

function gridToolContract(name, capability) {
  return {
    name,
    capability,
    description: `Execute ${capability}.`,
    input_schema: {
      type: "object",
      properties: {},
      additionalProperties: false,
    },
  };
}

async function readPatchText() {
  return import("node:fs/promises").then(({ readFile }) =>
    readFile(join(ROOT, "configs/runtime/patches/pi-0.80.6-before-model-request.patch"), "utf8"),
  );
}
