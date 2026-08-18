import { defineTool } from "@earendil-works/pi-coding-agent";
import { Type } from "@earendil-works/pi-ai";
import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { isAbsolute, relative, resolve } from "node:path";
import { readFileSync, realpathSync } from "node:fs";
import { readFile, realpath } from "node:fs/promises";

import { configureModelRequestCapture } from "./model-request-capture.mjs";

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
        }, contract.capability);
      }
      if (response.ok !== true) {
        const details = canonicalToolResult(contract.capability, response);
        return {
          content: [{ type: "text", text: JSON.stringify(response) }],
          details,
          isError: true,
        };
      }
      return {
        content: [{ type: "text", text: JSON.stringify(response) }],
        details: canonicalToolResult(contract.capability, response),
      };
    },
  });
}

export default function domainToolsExtension(pi) {
  const paths = runtimePaths(process.env);
  if (
    paths.trajectoryRequestsPath !== undefined &&
    paths.trajectoryCaptureStatePath !== undefined &&
    paths.trajectoryAllowedRefsPath !== undefined &&
    paths.trajectoryAcksPath !== undefined
  ) {
    configureModelRequestCapture(pi, {
      requestsPath: paths.trajectoryRequestsPath,
      activeTurnPath: paths.activeTurnPath,
      captureStatePath: paths.trajectoryCaptureStatePath,
      allowedRefsPath: paths.trajectoryAllowedRefsPath,
      acknowledgementsPath: paths.trajectoryAcksPath,
      runtime: paths.piRuntime,
    });
  }
  const catalog = readJsonSync(paths.toolCatalogPath);
  for (const contract of catalog.tools) {
    if (contract.name === "grid_record_decision") {
      continue;
    }
    pi.registerTool(createGridTool(contract, (payload) => runGridctl(payload, paths.workspacePath)));
  }
  pi.registerTool(createGuideTool(paths.guideIndexPath));
  if (paths.analysisContextViewPath !== undefined) {
    pi.registerTool(createAnalysisContextTool(paths.analysisContextViewPath));
  }
  if (paths.trajectoryAllowedRefsPath !== undefined && paths.activeTurnPath !== undefined) {
    pi.registerTool(createRecordDecisionTool(paths.trajectoryAllowedRefsPath, paths.activeTurnPath));
  }
}

function runGridctl(payload, workspacePath = requiredExistingRealPath(process.env, "GRID_AGENT_WORKSPACE")) {
  return new Promise((resolveResponse) => {
    const child = spawn("gridctl", ["request", "--workspace", workspacePath], {
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
  const guideIndex = readJsonSync(guideIndexPath);
  const resourceIds = Object.keys(guideIndex.resources ?? {}).sort();
  const resourceIdSchema = {
    type: "string",
    description: `Published resource ids: ${resourceIds.join(", ") || "none"}.`,
  };
  if (resourceIds.length > 0) {
    resourceIdSchema.enum = resourceIds;
  } else {
    resourceIdSchema.pattern = "a^";
  }
  return defineTool({
    name: "grid_guide_open",
    label: "grid_guide_open",
    description: `Open a published grid-analysis guide by resource id. Published ids: ${resourceIds.join(", ") || "none"}.`,
    parameters: Type.Unsafe({
      type: "object",
      additionalProperties: false,
      required: ["resource_id"],
      properties: { resource_id: resourceIdSchema },
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
        }, "grid_guide_open");
      }
      const guideIndex = await readJson(guideIndexPath);
      const root = await realpath(String(guideIndex.root));
      const resourcePath = guideIndex.resources?.[params.resource_id];
      if (typeof resourcePath !== "string") {
        return toolError({
          code: "guide_not_found",
          phase: "resolve",
          message: "guide resource is not published",
        }, "grid_guide_open");
      }
      let resolvedPath;
      try {
        resolvedPath = await realpath(resourcePath);
      } catch {
        return toolError({
          code: "guide_path_rejected",
          phase: "resolve",
          message: "guide resource path is unavailable",
        }, "grid_guide_open");
      }
      if (!isInside(resolvedPath, root)) {
        return toolError({
          code: "guide_path_rejected",
          phase: "resolve",
          message: "guide resource path is outside the published guide root",
        }, "grid_guide_open");
      }
      const text = await readFile(resolvedPath, "utf8");
      const result = { resource_id: params.resource_id, text };
      return {
        content: [{ type: "text", text }],
        details: {
          event: "tool_result",
          capability: "grid_guide_open",
          ok: true,
          result,
          evidence_refs: [],
        },
      };
    },
  });
}

function createAnalysisContextTool(analysisContextViewPath) {
  return defineTool({
    name: "grid_analysis_context_get",
    label: "grid_analysis_context_get",
    description: "Return the controller-generated bounded read-only analysis context view.",
    parameters: Type.Object({}),
    async execute() {
      const result = await readJson(analysisContextViewPath);
      return {
        content: [{ type: "text", text: JSON.stringify(result) }],
        details: {
          event: "tool_result",
          capability: "grid_analysis_context_get",
          ok: true,
          result,
          evidence_refs: [],
        },
      };
    },
  });
}

function createRecordDecisionTool(allowedRefsPath, activeTurnPath) {
  return defineTool({
    name: "grid_record_decision",
    label: "grid_record_decision",
    description: "Declare bounded agent intent. This is not simulator truth and creates no evidence.",
    parameters: Type.Object(
      {
        intent: Type.String({ minLength: 1, maxLength: 500 }),
        decision: Type.String({ minLength: 1, maxLength: 500 }),
        next_action: Type.String({ minLength: 1, maxLength: 500 }),
        refs: Type.Array(Type.String({ minLength: 1 }), { maxItems: 20 }),
      },
      { additionalProperties: false },
    ),
    async execute(_id, params) {
      const invalid = decisionValidationError(params);
      if (invalid !== undefined) {
        return toolError(
          { code: "invalid_decision", phase: "validate", message: invalid },
          "grid_record_decision",
        );
      }
      await readActiveTurn(activeTurnPath);
      let known;
      try {
        known = await readAllowedRefs(allowedRefsPath);
      } catch (error) {
        return toolError(
          {
            code: "decision_state_invalid",
            phase: "resolve",
            message: error instanceof Error ? error.message : String(error),
          },
          "grid_record_decision",
        );
      }
      if (params.refs.some((reference) => !known.has(reference))) {
        return toolError(
          {
            code: "unknown_decision_ref",
            phase: "resolve",
            message: "decision refs must be known in the current run",
          },
          "grid_record_decision",
        );
      }
      const result = {
        intent: params.intent,
        decision: params.decision,
        next_action: params.next_action,
        refs: [...params.refs],
      };
      const details = {
        event: "tool_result",
        capability: "grid_record_decision",
        ok: true,
        result,
        evidence_refs: [],
      };
      return {
        content: [{ type: "text", text: JSON.stringify(result) }],
        details,
      };
    },
  });
}

function decisionValidationError(params) {
  for (const name of ["intent", "decision", "next_action"]) {
    if (
      typeof params?.[name] !== "string" ||
      params[name].length < 1 ||
      params[name].length > 500
    ) {
      return `${name} must contain 1 to 500 characters`;
    }
  }
  if (
    !Array.isArray(params?.refs) ||
    params.refs.length > 20 ||
    !params.refs.every((reference) => typeof reference === "string" && reference.length > 0)
  ) {
    return "refs must contain at most 20 non-empty strings";
  }
  return undefined;
}

async function readAllowedRefs(path) {
  const document = await readJson(path);
  if (
    !document ||
    !Array.isArray(document.refs) ||
    !document.refs.every((reference) => typeof reference === "string" && reference.length > 0)
  ) {
    throw new Error("trajectory allowed refs document is invalid");
  }
  return new Set(document.refs);
}

function runtimePaths(env) {
  const workspacePath = requiredExistingRealPath(env, "GRID_AGENT_WORKSPACE");
  const toolCatalogPath = requiredExistingRealPath(env, "GRID_AGENT_TOOL_CATALOG");
  const guideIndexPath = requiredExistingRealPath(env, "GRID_AGENT_GUIDE_INDEX");
  const activeTurnPath = optionalWritableRealPath(env, "GRID_AGENT_ACTIVE_TURN");
  const analysisContextViewPath = optionalExistingRealPath(env, "GRID_AGENT_ANALYSIS_CONTEXT_VIEW");
  const trajectoryRequestsPath = optionalExistingRealPath(env, "GRID_AGENT_TRAJECTORY_REQUESTS");
  const trajectoryCaptureStatePath = optionalExistingRealPath(
    env,
    "GRID_AGENT_TRAJECTORY_CAPTURE_STATE",
  );
  const trajectoryAllowedRefsPath = optionalExistingRealPath(
    env,
    "GRID_AGENT_TRAJECTORY_ALLOWED_REFS",
  );
  const trajectoryAcksPath = optionalExistingRealPath(env, "GRID_AGENT_TRAJECTORY_ACKS");
  const trajectoryPaths = [
    trajectoryRequestsPath,
    trajectoryCaptureStatePath,
    trajectoryAllowedRefsPath,
    trajectoryAcksPath,
  ];
  const trajectoryConfigured = trajectoryPaths.every((path) => path !== undefined);
  if (trajectoryPaths.some((path) => path !== undefined) && !trajectoryConfigured) {
    throw new Error("trajectory capture requires all four trajectory paths");
  }
  if (trajectoryConfigured && activeTurnPath === undefined) {
    throw new Error("trajectory capture requires GRID_AGENT_ACTIVE_TURN");
  }
  for (const [name, candidate] of [
    ["GRID_AGENT_TOOL_CATALOG", toolCatalogPath],
    ["GRID_AGENT_GUIDE_INDEX", guideIndexPath],
    ["GRID_AGENT_ACTIVE_TURN", activeTurnPath],
    ["GRID_AGENT_ANALYSIS_CONTEXT_VIEW", analysisContextViewPath],
    ["GRID_AGENT_TRAJECTORY_REQUESTS", trajectoryRequestsPath],
    ["GRID_AGENT_TRAJECTORY_CAPTURE_STATE", trajectoryCaptureStatePath],
    ["GRID_AGENT_TRAJECTORY_ALLOWED_REFS", trajectoryAllowedRefsPath],
  ]) {
    if (candidate !== undefined && !isInside(candidate, workspacePath)) {
      throw new Error(`${name} resolved path ${candidate} is outside GRID_AGENT_WORKSPACE`);
    }
  }
  return {
    workspacePath,
    toolCatalogPath,
    guideIndexPath,
    activeTurnPath,
    analysisContextViewPath,
    trajectoryRequestsPath,
    trajectoryCaptureStatePath,
    trajectoryAllowedRefsPath,
    trajectoryAcksPath,
    piRuntime: runtimeIdentity(env),
  };
}

function runtimeIdentity(env) {
  if (
    env.GRID_AGENT_PI_CODING_AGENT_VERSION === undefined &&
    env.GRID_AGENT_PI_AI_VERSION === undefined &&
    env.GRID_AGENT_PI_SOURCE_COMMIT === undefined &&
    env.GRID_AGENT_PI_PATCH_SET_SHA256 === undefined
  ) {
    return undefined;
  }
  return {
    pi_coding_agent_version: requiredString(env, "GRID_AGENT_PI_CODING_AGENT_VERSION"),
    pi_ai_version: requiredString(env, "GRID_AGENT_PI_AI_VERSION"),
    pi_source_commit: requiredString(env, "GRID_AGENT_PI_SOURCE_COMMIT"),
    pi_patch_set_sha256: requiredString(env, "GRID_AGENT_PI_PATCH_SET_SHA256"),
  };
}

function requiredString(env, name) {
  const value = env[name];
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${name} must be a non-empty string`);
  }
  return value;
}

function requiredAbsolutePath(env, name) {
  const value = env[name];
  if (typeof value !== "string" || value.length === 0 || !isAbsolute(value)) {
    throw new Error(`${name} must be an absolute path`);
  }
  return resolve(value);
}

function requiredExistingRealPath(env, name) {
  const path = requiredAbsolutePath(env, name);
  try {
    return realpathSync(path);
  } catch (error) {
    throw new Error(`${name} must resolve to an existing path: ${error.message}`);
  }
}

function optionalExistingRealPath(env, name) {
  if (env[name] === undefined || env[name] === "") {
    return undefined;
  }
  return requiredExistingRealPath(env, name);
}

function optionalWritableRealPath(env, name) {
  if (env[name] === undefined || env[name] === "") {
    return undefined;
  }
  return requiredExistingRealPath(env, name);
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

function canonicalToolResult(capability, response) {
  if (response.ok === true) {
    const result = response.result ?? {};
    return {
      event: "tool_result",
      capability,
      ok: true,
      result,
      evidence_refs: evidenceRefs(result),
    };
  }
  const error = response.error ?? {};
  return {
    event: "tool_result",
    capability,
    ok: false,
    result: {},
    error,
    evidence_refs: evidenceRefs(error),
  };
}

function evidenceRefs(value) {
  const refs = [];
  if (typeof value?.evidence_ref === "string") {
    refs.push(value.evidence_ref);
  }
  if (Array.isArray(value?.evidence_refs)) {
    refs.push(...value.evidence_refs.filter((reference) => typeof reference === "string"));
  }
  return [...new Set(refs)];
}

function toolError(error, capability) {
  const details = {
    event: "tool_result",
    capability,
    ok: false,
    result: {},
    error,
    evidence_refs: [],
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

async function readActiveTurn(path) {
  const activeTurn = await readJson(path);
  if (typeof activeTurn?.turn_id !== "string" || typeof activeTurn?.turn_nonce !== "string") {
    throw new Error("GRID_AGENT_ACTIVE_TURN must contain turn_id and turn_nonce");
  }
  return {
    turn_id: activeTurn.turn_id,
    turn_nonce: activeTurn.turn_nonce,
  };
}
