import { createHash, randomUUID } from "node:crypto";
import { mkdir, open, readFile, rename, unlink } from "node:fs/promises";
import { writeSync } from "node:fs";
import { basename, dirname, join } from "node:path";

const TURN_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;
const CONTENT_HASH_PATTERN = /^[0-9a-f]{64}$/;
const RUNTIME_SOURCE_COMMIT_PATTERN = /^[0-9a-f]{40}$/;
const PUBLIC_OPTION_KEYS = [
  "reasoning",
  "thinkingBudgets",
  "temperature",
  "maxTokens",
  "transport",
  "cacheRetention",
  "timeoutMs",
  "websocketConnectTimeoutMs",
  "maxRetries",
  "maxRetryDelayMs",
];
const PUBLIC_OPTION_KEY_SET = new Set(PUBLIC_OPTION_KEYS);
const REASONING_VALUES = new Set(["minimal", "low", "medium", "high", "xhigh", "max"]);
const TRANSPORT_VALUES = new Set(["sse", "websocket", "websocket-cached", "auto"]);
const CACHE_RETENTION_VALUES = new Set(["none", "short", "long"]);
const THINKING_BUDGET_KEYS = ["minimal", "low", "medium", "high"];
const THINKING_BUDGET_KEY_SET = new Set(THINKING_BUDGET_KEYS);
const NUMERIC_OPTION_KEYS = new Set([
  "temperature",
  "maxTokens",
  "timeoutMs",
  "websocketConnectTimeoutMs",
  "maxRetries",
  "maxRetryDelayMs",
]);

export class CanonicalRequestContractError extends Error {
  constructor(message) {
    super(`canonical model request contract violation: ${message}`);
    this.name = "CanonicalRequestContractError";
  }
}

export function configureModelRequestCapture(pi, paths, fatal = captureFatal) {
  let requestIndex = 0;
  const runtime = validateRuntimeIdentity(paths.runtime ?? defaultRuntimeIdentity());
  pi.on("before_model_request", async (event) => {
    try {
      requestIndex += 1;
      const turn = validateActiveTurn(await readJson(paths.activeTurnPath));
      const state = validateCaptureState(await readJson(paths.captureStatePath));
      const semanticRequest = canonicalSemanticRequest(event);
      const requestId = `${turn.turn_id}-r${String(requestIndex).padStart(3, "0")}`;
      const document = {
        schema_version: "grid-model-request-input/2.0",
        request_id: requestId,
        request_index: requestIndex,
        turn_id: turn.turn_id,
        captured_at: new Date().toISOString(),
        source_event_sequences: state.source_event_sequences,
        context_revision: state.context_revision,
        context_state_hash: state.context_state_hash,
        runtime,
        semantic_request: semanticRequest,
        semantic_request_sha256: sha256Canonical(semanticRequest),
      };
      await writeJsonAtomicFsync(join(paths.requestsPath, requestId, "input.json"), document);
      return undefined;
    } catch (error) {
      return fatal(
        `model request capture failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  });
}

export const configureTrajectoryCapture = configureModelRequestCapture;

export function captureFatal(message) {
  writeSync(process.stderr.fd, `${message}\n`);
  process.exit(86);
}

async function readJson(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

function defaultRuntimeIdentity() {
  return {
    pi_coding_agent_version: "0.80.6",
    pi_ai_version: "0.80.6",
    pi_source_commit: "2b3fda9921b5590f285165287bd442a25817f17b",
    pi_patch_set_sha256: "458794796163d70c71846a4f38a543bf2ed495547c5fd216b2f1e0d684e1da0e",
  };
}

function validateRuntimeIdentity(value) {
  if (!isPlainObject(value)) {
    throw new Error("invalid Pi runtime identity");
  }
  const runtime = {
    pi_coding_agent_version: requireString(value.pi_coding_agent_version, "pi_coding_agent_version"),
    pi_ai_version: requireString(value.pi_ai_version, "pi_ai_version"),
    pi_source_commit: requireString(value.pi_source_commit, "pi_source_commit"),
    pi_patch_set_sha256: requireString(value.pi_patch_set_sha256, "pi_patch_set_sha256"),
  };
  if (!RUNTIME_SOURCE_COMMIT_PATTERN.test(runtime.pi_source_commit)) {
    throw new Error("invalid Pi runtime source commit");
  }
  if (!CONTENT_HASH_PATTERN.test(runtime.pi_patch_set_sha256)) {
    throw new Error("invalid Pi runtime patch set hash");
  }
  return runtime;
}

function validateActiveTurn(value) {
  if (!isPlainObject(value) || typeof value.turn_id !== "string" || !TURN_ID_PATTERN.test(value.turn_id)) {
    throw new Error("unsafe turn_id in active turn state");
  }
  return value;
}

function validateCaptureState(value) {
  if (!isPlainObject(value)) {
    throw new Error("invalid trajectory capture state");
  }
  if (
    !Array.isArray(value.source_event_sequences) ||
    value.source_event_sequences.length === 0 ||
    !value.source_event_sequences.every(
      (sequence, index, sequences) =>
        Number.isSafeInteger(sequence) &&
        sequence > 0 &&
        (index === 0 || sequence > sequences[index - 1]),
    )
  ) {
    throw new Error("invalid trajectory capture state source_event_sequences");
  }
  if (!Number.isSafeInteger(value.context_revision) || value.context_revision < 0) {
    throw new Error("invalid trajectory capture state context_revision");
  }
  if (
    typeof value.context_state_hash !== "string" ||
    !CONTENT_HASH_PATTERN.test(value.context_state_hash)
  ) {
    throw new Error("invalid trajectory capture state context_state_hash");
  }
  return {
    source_event_sequences: [...value.source_event_sequences],
    context_revision: value.context_revision,
    context_state_hash: value.context_state_hash,
  };
}

function canonicalSemanticRequest(event) {
  if (!isPlainObject(event) || event.type !== "before_model_request") {
    throw new CanonicalRequestContractError("event must be before_model_request");
  }
  return {
    model: canonicalModel(event.model),
    context: canonicalContext(event.context),
    options: canonicalOptions(event.options ?? {}),
  };
}

function canonicalModel(model) {
  if (!isPlainObject(model)) {
    throw new CanonicalRequestContractError("model must be an object");
  }
  return {
    provider: requireString(model.provider, "model.provider"),
    api: requireString(model.api, "model.api"),
    id: requireString(model.id, "model.id"),
  };
}

function canonicalContext(context) {
  if (!isPlainObject(context)) {
    throw new CanonicalRequestContractError("context must be an object");
  }
  if (!Array.isArray(context.messages)) {
    throw new CanonicalRequestContractError("context.messages must be an array");
  }
  return {
    system_prompt: context.systemPrompt ?? null,
    messages: context.messages.map(canonicalMessage),
    tools: (context.tools ?? []).map(canonicalTool),
  };
}

function canonicalOptions(options) {
  if (!isPlainObject(options)) {
    throw new CanonicalRequestContractError("options must be an object");
  }
  for (const key of Object.keys(options)) {
    if (!PUBLIC_OPTION_KEY_SET.has(key)) {
      throw new CanonicalRequestContractError(`unknown option: ${key}`);
    }
  }
  const projected = {};
  for (const key of PUBLIC_OPTION_KEYS) {
    if (options[key] !== undefined) {
      projected[key] = canonicalOptionValue(key, options[key]);
    }
  }
  return projected;
}

function canonicalOptionValue(key, value) {
  switch (key) {
    case "reasoning":
      return requireEnum(value, "options.reasoning", REASONING_VALUES);
    case "thinkingBudgets":
      return canonicalThinkingBudgets(value);
    case "transport":
      return requireEnum(value, "options.transport", TRANSPORT_VALUES);
    case "cacheRetention":
      return requireEnum(value, "options.cacheRetention", CACHE_RETENTION_VALUES);
    default:
      if (NUMERIC_OPTION_KEYS.has(key)) {
        return requireNonNegativeFiniteNumber(value, `options.${key}`);
      }
      throw new CanonicalRequestContractError(`unknown option: ${key}`);
  }
}

function canonicalThinkingBudgets(value) {
  if (!isPlainObject(value)) {
    throw new CanonicalRequestContractError("options.thinkingBudgets must be an object");
  }
  for (const key of Object.keys(value)) {
    if (!THINKING_BUDGET_KEY_SET.has(key)) {
      throw new CanonicalRequestContractError(`unknown thinking budget: ${key}`);
    }
  }
  const projected = {};
  for (const key of THINKING_BUDGET_KEYS) {
    if (value[key] !== undefined) {
      projected[key] = requireNonNegativeFiniteNumber(value[key], `options.thinkingBudgets.${key}`);
    }
  }
  return projected;
}

function canonicalMessage(message) {
  if (!isPlainObject(message)) {
    throw new CanonicalRequestContractError("message must be an object");
  }
  switch (message.role) {
    case "user":
      return {
        role: "user",
        content: canonicalUserContent(message.content),
      };
    case "assistant":
      return {
        role: "assistant",
        content: requireArray(message.content, "assistant.content").map(canonicalAssistantContent),
      };
    case "toolResult":
      return {
        role: "toolResult",
        toolCallId: requireString(message.toolCallId, "toolResult.toolCallId"),
        toolName: requireString(message.toolName, "toolResult.toolName"),
        content: requireArray(message.content, "toolResult.content").map(canonicalUserContentBlock),
        details: validateJsonLeaf(message.details ?? null, "toolResult.details"),
        isError: requireBoolean(message.isError, "toolResult.isError"),
      };
    default:
      throw new CanonicalRequestContractError(`unknown message role: ${String(message.role)}`);
  }
}

function canonicalUserContent(content) {
  if (typeof content === "string") {
    return [{ type: "text", text: content }];
  }
  return requireArray(content, "user.content").map(canonicalUserContentBlock);
}

function canonicalUserContentBlock(content) {
  if (!isPlainObject(content)) {
    throw new CanonicalRequestContractError("content block must be an object");
  }
  switch (content.type) {
    case "text":
      return { type: "text", text: requireString(content.text, "text.text") };
    case "image":
      return {
        type: "image",
        data: requireString(content.data, "image.data"),
        mimeType: requireString(content.mimeType, "image.mimeType"),
      };
    default:
      throw new CanonicalRequestContractError(`unknown content type: ${String(content.type)}`);
  }
}

function canonicalAssistantContent(content) {
  if (!isPlainObject(content)) {
    throw new CanonicalRequestContractError("assistant content block must be an object");
  }
  switch (content.type) {
    case "text":
      return { type: "text", text: requireString(content.text, "text.text") };
    case "thinking":
      return { type: "thinking", redacted: true };
    case "toolCall":
      return {
        type: "toolCall",
        id: requireString(content.id, "toolCall.id"),
        name: requireString(content.name, "toolCall.name"),
        arguments: validateJsonLeaf(content.arguments, "toolCall.arguments"),
      };
    default:
      throw new CanonicalRequestContractError(`unknown assistant content type: ${String(content.type)}`);
  }
}

function canonicalTool(tool) {
  if (!isPlainObject(tool)) {
    throw new CanonicalRequestContractError("tool must be an object");
  }
  return {
    name: requireString(tool.name, "tool.name"),
    description: requireString(tool.description, "tool.description"),
    parameters: validateJsonLeaf(tool.parameters, "tool.parameters"),
  };
}

function requireString(value, name) {
  if (typeof value !== "string" || value.length === 0) {
    throw new CanonicalRequestContractError(`${name} must be a non-empty string`);
  }
  return value;
}

function requireBoolean(value, name) {
  if (typeof value !== "boolean") {
    throw new CanonicalRequestContractError(`${name} must be a boolean`);
  }
  return value;
}

function requireEnum(value, name, allowed) {
  if (typeof value !== "string" || !allowed.has(value)) {
    throw new CanonicalRequestContractError(`${name} must be a supported value`);
  }
  return value;
}

function requireNonNegativeFiniteNumber(value, name) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new CanonicalRequestContractError(`${name} must be a finite non-negative number`);
  }
  return value;
}

function requireArray(value, name) {
  if (!Array.isArray(value)) {
    throw new CanonicalRequestContractError(`${name} must be an array`);
  }
  return value;
}

function validateJsonLeaf(value, path, ancestors = new Set()) {
  if (value === undefined) {
    throw new CanonicalRequestContractError(`${path} contains undefined`);
  }
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new CanonicalRequestContractError(`${path} contains a non-finite number`);
    }
    return value;
  }
  if (typeof value !== "object") {
    throw new CanonicalRequestContractError(`${path} contains a non-JSON value`);
  }
  if (ancestors.has(value)) {
    throw new CanonicalRequestContractError(`${path} contains a cycle`);
  }

  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      if (Object.keys(value).length !== value.length) {
        throw new CanonicalRequestContractError(`${path} contains a sparse array`);
      }
      return value.map((item, index) => validateJsonLeaf(item, `${path}[${index}]`, ancestors));
    }
    if (!isPlainObject(value) || Reflect.ownKeys(value).some((key) => typeof key !== "string")) {
      throw new CanonicalRequestContractError(`${path} contains a non-plain object`);
    }
    const normalized = {};
    for (const [key, item] of Object.entries(value)) {
      normalized[key] = validateJsonLeaf(item, `${path}.${key}`, ancestors);
    }
    return normalized;
  } finally {
    ancestors.delete(value);
  }
}

function sha256Canonical(value) {
  return createHash("sha256").update(JSON.stringify(sortJson(value)), "utf8").digest("hex");
}

function isPlainObject(value) {
  if (value === null || typeof value !== "object") {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

async function writeJsonAtomicFsync(path, payload) {
  const parent = dirname(path);
  const requestRoot = dirname(parent);
  try {
    await mkdir(parent);
  } catch (error) {
    if (error?.code === "EEXIST") {
      throw new Error(`request path already exists: ${path}`);
    }
    throw error;
  }
  await syncDirectory(requestRoot);

  const temporaryPath = join(
    parent,
    `.${basename(path)}.${process.pid}.${randomUUID()}.tmp`,
  );
  let handle;
  try {
    handle = await open(temporaryPath, "wx", 0o600);
    await handle.writeFile(`${JSON.stringify(sortJson(payload))}\n`, "utf8");
    await handle.sync();
    await handle.close();
    handle = undefined;
    await rename(temporaryPath, path);
    await syncDirectory(parent);
  } catch (error) {
    if (handle !== undefined) {
      await handle.close().catch(() => undefined);
    }
    await unlink(temporaryPath).catch(() => undefined);
    throw error;
  }
}

async function syncDirectory(path) {
  const handle = await open(path, "r");
  try {
    await handle.sync();
  } finally {
    await handle.close();
  }
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
