import { createBashTool, defineTool } from "@earendil-works/pi-coding-agent";
import { Type } from "@earendil-works/pi-ai";
import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";

const CANONICAL_SECRET_NAMES = [
  "OPENAI_API_KEY",
  "OPENROUTER_API_KEY",
  "DEEPSEEK_API_KEY",
  "MINIMAX_API_KEY",
];

export function sanitizeEnvironment(env, selectedNames = []) {
  const blocked = new Set([
    ...CANONICAL_SECRET_NAMES,
    ...selectedNames,
    "GRID_AGENT_SECRET_ENV_NAMES",
  ]);
  return Object.fromEntries(
    Object.entries(env).filter(([name]) => !blocked.has(name)),
  );
}

export function buildGridRequest(operation, params, requestId = randomUUID()) {
  return { protocol_version: "1.0", request_id: requestId, operation, arguments: params };
}

function runGridctl(payload) {
  return new Promise((resolve) => {
    const child = spawn("gridctl", ["request", "--workspace", process.env.GRID_AGENT_WORKSPACE], {
      env: sanitizeEnvironment(process.env, (process.env.GRID_AGENT_SECRET_ENV_NAMES ?? "").split(",")),
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", (error) => resolve({ ok: false, error: error.message }));
    child.on("close", () => {
      try { resolve(JSON.parse(stdout)); }
      catch { resolve({ ok: false, error: stderr || stdout || "gridctl returned no JSON" }); }
    });
    child.stdin.end(JSON.stringify(payload));
  });
}

const gridQueryTool = defineTool({
  name: "grid_query",
  label: "Grid query",
  description: "Run one verified IEEE-39 simulator operation. Use this instead of bash for every gridctl request.",
  parameters: Type.Object({
    operation: Type.Union([
      Type.Literal("capabilities.list"), Type.Literal("capabilities.describe"), Type.Literal("network.open"),
      Type.Literal("network.describe"), Type.Literal("element.resolve"), Type.Literal("powerflow.run_ac"),
      Type.Literal("results.lines"), Type.Literal("contingency.run_lines"),
    ]),
    arguments: Type.Object({}, { additionalProperties: true }),
  }),
  async execute(_id, params) {
    const response = await runGridctl(buildGridRequest(params.operation, params.arguments));
    return { content: [{ type: "text", text: JSON.stringify(response) }], details: response, isError: response.ok !== true };
  },
});

export default function hardenedBashExtension(pi) {
  const selectedNames = (process.env.GRID_AGENT_SECRET_ENV_NAMES ?? "")
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
  const bashTool = createBashTool(process.cwd(), {
    spawnHook: ({ command, cwd, env }) => ({
      command,
      cwd,
      env: sanitizeEnvironment(env, selectedNames),
    }),
  });
  pi.registerTool({ ...bashTool });
  pi.registerTool(gridQueryTool);
}
