import { createBashTool } from "@earendil-works/pi-coding-agent";

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
}
