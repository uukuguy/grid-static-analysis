import { defineTool } from "@earendil-works/pi-coding-agent";
import { Type } from "@earendil-works/pi-ai";
import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { dirname, isAbsolute, relative, resolve } from "node:path";
import { readFileSync } from "node:fs";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";

const CANONICAL_SECRET_NAMES = [
  "OPENAI_API_KEY",
  "OPENROUTER_API_KEY",
  "DEEPSEEK_API_KEY",
  "MINIMAX_API_KEY",
];
const RESOURCE_ID_PATTERN = /^[a-z0-9][a-z0-9-]+$/;
const ENCODED_SEPARATOR_PATTERN = /%(?:2f|5c)/i;

export function sanitizeEnvironment(env, selectedNames = []) {
  const blocked = new Set([
    ...CANONICAL_SECRET_NAMES,
    ...selectedNames,
    "GRID_AGENT_SECRET_ENV_NAMES",
  ]);
  return Object.fromEntries(
    Object.entries(env).filter(([name]) => !blocked.has(name) && !isCredentialName(name)),
  );
}

export function buildGridRequest(capability, params, requestId = randomUUID()) {
  return {
    protocol: "grid-capability",
    protocol_version: "1.0",
    request_id: requestId,
    capability,
    arguments: params,
  };
}

export function createGridTool(contract, runner = runGridctl) {
  return defineTool({
    name: contract.name,
    label: contract.name,
    description: contract.description,
    parameters: Type.Unsafe(contract.input_schema),
    async execute(_id, params) {
      const payload = buildGridRequest(contract.capability, params);
      const response = await runner(payload);
      if (!isCorrelatedResponse(response, payload.request_id)) {
        return toolError({
          code: "response_correlation_mismatch",
          phase: "parse",
          message: "gridctl response did not match the request id",
          details: { expected_request_id: payload.request_id, response },
        });
      }
      if (response.ok !== true) {
        return {
          content: [{ type: "text", text: JSON.stringify(response) }],
          details: response,
          isError: true,
        };
      }
      return { content: [{ type: "text", text: JSON.stringify(response) }], details: response };
    },
  });
}

export default function domainToolsExtension(pi) {
  const paths = runtimePaths(process.env);
  const catalog = readJsonSync(paths.toolCatalogPath);
  for (const contract of catalog.tools) {
    pi.registerTool(createGridTool(contract));
  }
  pi.registerTool(createGuideTool(paths.guideIndexPath));
  pi.registerTool(createSubmitAnswerTool(paths.answerDraftPath));
}

function runGridctl(payload) {
  return new Promise((resolveResponse) => {
    const child = spawn("gridctl", ["request", "--workspace", process.env.GRID_AGENT_WORKSPACE], {
      env: sanitizeEnvironment(process.env, selectedSecretNames(process.env)),
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", (error) => {
      resolveResponse(gridctlTransportError(payload.request_id, error.message));
    });
    child.on("close", () => {
      try {
        resolveResponse(JSON.parse(stdout));
      } catch {
        resolveResponse(gridctlTransportError(payload.request_id, stderr || stdout || "gridctl returned no JSON"));
      }
    });
    child.stdin.end(JSON.stringify(payload));
  });
}

function createGuideTool(guideIndexPath) {
  return defineTool({
    name: "grid_guide_open",
    label: "grid_guide_open",
    description: "Open a published grid-analysis guide by resource id.",
    parameters: Type.Object({
      resource_id: Type.String(),
    }),
    async execute(_id, params) {
      if (
        !RESOURCE_ID_PATTERN.test(params.resource_id) ||
        ENCODED_SEPARATOR_PATTERN.test(params.resource_id)
      ) {
        return toolError({
          code: "guide_not_found",
          phase: "resolve",
          message: "guide resource is not published",
        });
      }
      const guideIndex = await readJson(guideIndexPath);
      const root = resolve(String(guideIndex.root));
      const resourcePath = guideIndex.resources?.[params.resource_id];
      if (typeof resourcePath !== "string") {
        return toolError({
          code: "guide_not_found",
          phase: "resolve",
          message: "guide resource is not published",
        });
      }
      const resolvedPath = resolve(resourcePath);
      if (!isInside(resolvedPath, root)) {
        return toolError({
          code: "guide_path_rejected",
          phase: "resolve",
          message: "guide resource path is outside the published guide root",
        });
      }
      const text = await readFile(resolvedPath, "utf8");
      const result = { resource_id: params.resource_id, text };
      return { content: [{ type: "text", text }], details: result };
    },
  });
}

function createSubmitAnswerTool(answerDraftPath) {
  return defineTool({
    name: "grid_submit_answer",
    label: "grid_submit_answer",
    description: "Submit the final answer draft and claimed evidence references.",
    parameters: Type.Object({
      answer_output: Type.String(),
      claim_evidence_refs: Type.Array(Type.String()),
    }),
    async execute(_id, params) {
      const payload = {
        answer_output: params.answer_output,
        claim_evidence_refs: params.claim_evidence_refs,
      };
      await writeJsonAtomic(answerDraftPath, payload);
      return {
        content: [{ type: "text", text: JSON.stringify({ ok: true }) }],
        details: { ok: true, path: answerDraftPath },
      };
    },
  });
}

function runtimePaths(env) {
  const workspacePath = requiredResolvedPath(env, "GRID_AGENT_WORKSPACE");
  const toolCatalogPath = requiredResolvedPath(env, "GRID_AGENT_TOOL_CATALOG");
  const guideIndexPath = requiredResolvedPath(env, "GRID_AGENT_GUIDE_INDEX");
  const answerDraftPath = requiredResolvedPath(env, "GRID_AGENT_ANSWER_DRAFT");
  for (const candidate of [toolCatalogPath, guideIndexPath, answerDraftPath]) {
    if (!isInside(candidate, workspacePath)) {
      throw new Error(`${candidate} is outside GRID_AGENT_WORKSPACE`);
    }
  }
  return { workspacePath, toolCatalogPath, guideIndexPath, answerDraftPath };
}

function requiredResolvedPath(env, name) {
  const value = env[name];
  if (typeof value !== "string" || value.length === 0 || !isAbsolute(value)) {
    throw new Error(`${name} must be an absolute path`);
  }
  return resolve(value);
}

function isInside(candidate, root) {
  const relationship = relative(root, candidate);
  return relationship === "" || (!relationship.startsWith("..") && !isAbsolute(relationship));
}

function selectedSecretNames(env) {
  return (env.GRID_AGENT_SECRET_ENV_NAMES ?? "")
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
}

function isCredentialName(name) {
  return /(API_KEY|TOKEN|SECRET|AUTHORIZATION|CREDENTIAL|PASSWORD|PRIVATE_KEY)$/i.test(name);
}

function isCorrelatedResponse(response, requestId) {
  return (
    response &&
    response.protocol === "grid-capability" &&
    response.protocol_version === "1.0" &&
    response.request_id === requestId
  );
}

function gridctlTransportError(requestId, message) {
  return {
    protocol: "grid-capability",
    protocol_version: "1.0",
    request_id: requestId,
    ok: false,
    error: {
      code: "gridctl_transport_error",
      phase: "execute",
      message,
    },
  };
}

function toolError(error) {
  const details = {
    protocol: "grid-capability",
    protocol_version: "1.0",
    ok: false,
    error,
  };
  return {
    content: [{ type: "text", text: JSON.stringify(details) }],
    details,
    isError: true,
  };
}

function readJsonSync(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

async function readJson(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

async function writeJsonAtomic(path, payload) {
  await mkdir(dirname(path), { recursive: true });
  const temp = `${path}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(temp, JSON.stringify(payload, null, 2) + "\n", "utf8");
  await rename(temp, path);
}
