import { randomUUID } from "node:crypto";
import { mkdir, open, readFile, rename, unlink } from "node:fs/promises";
import { basename, dirname, join } from "node:path";

const TURN_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;
const CONTENT_HASH_PATTERN = /^[0-9a-f]{64}$/;
const CREDENTIAL_KEY_PATTERN = /(?:api[_-]?key|token|secret|authorization|credential|password|private[_-]?key)$/i;
const HIDDEN_REASONING_KEYS = new Set([
  "chain_of_thought",
  "hidden_reasoning",
  "reasoning_content",
  "thinking_content",
]);
const OMIT_JSON_PROPERTY = Symbol("omit-json-property");

export function configureTrajectoryCapture(pi, paths, fatal = captureFatal) {
  let requestIndex = 0;
  pi.on("before_provider_request", async (event) => {
    try {
      requestIndex += 1;
      const turn = validateActiveTurn(await readJson(paths.activeTurnPath));
      const state = validateCaptureState(await readJson(paths.captureStatePath));
      validatePublicIdentifier(paths.providerId, "providerId");
      validatePublicIdentifier(paths.modelId, "modelId");
      const providerPayload = normalizeJsonPayload(event?.payload);

      const requestId = `${turn.turn_id}-r${String(requestIndex).padStart(3, "0")}`;
      const document = {
        schema_version: "grid-model-request-input/1.0",
        request_id: requestId,
        request_index: requestIndex,
        turn_id: turn.turn_id,
        provider: paths.providerId,
        model: paths.modelId,
        captured_at: new Date().toISOString(),
        source_event_sequences: state.source_event_sequences,
        context_revision: state.context_revision,
        context_state_hash: state.context_state_hash,
        provider_payload: providerPayload,
      };
      await writeJsonAtomicFsync(join(paths.requestsPath, requestId, "input.json"), document);
      return undefined;
    } catch (error) {
      return fatal(
        `trajectory request capture failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  });
}

export function captureFatal(message) {
  process.stderr.write(`${message}\n`);
  process.exit(86);
}

async function readJson(path) {
  return JSON.parse(await readFile(path, "utf8"));
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

function validatePublicIdentifier(value, name) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${name} must be a non-empty public identifier`);
  }
}

function normalizeJsonPayload(value, ancestors = new Set(), arrayValue = false) {
  if (value === undefined) {
    return arrayValue ? null : OMIT_JSON_PROPERTY;
  }
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new Error("non-JSON provider payload value");
    }
    return value;
  }
  if (typeof value !== "object") {
    throw new Error("non-JSON provider payload value");
  }
  if (ancestors.has(value)) {
    throw new Error("non-JSON provider payload cycle");
  }

  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      if (Object.keys(value).length !== value.length) {
        throw new Error("non-JSON provider payload array");
      }
      return value.map((item) => normalizeJsonPayload(item, ancestors, true));
    }
    if (!isPlainObject(value) || Reflect.ownKeys(value).some((key) => typeof key !== "string")) {
      throw new Error("non-JSON provider payload object");
    }
    const normalized = {};
    for (const [key, item] of Object.entries(value)) {
      const normalizedKey = normalizeKey(key);
      if (CREDENTIAL_KEY_PATTERN.test(key) || HIDDEN_REASONING_KEYS.has(normalizedKey)) {
        throw new Error(`prohibited provider payload key: ${key}`);
      }
      const normalizedItem = normalizeJsonPayload(item, ancestors);
      if (normalizedItem !== OMIT_JSON_PROPERTY) {
        normalized[key] = normalizedItem;
      }
    }
    return normalized;
  } finally {
    ancestors.delete(value);
  }
}

function normalizeKey(value) {
  return value
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/[^A-Za-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .toLowerCase();
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
