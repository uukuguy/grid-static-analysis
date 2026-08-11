import test from "node:test";
import assert from "node:assert/strict";

import { sanitizeEnvironment } from "../src/hardened-bash.mjs";
import { buildGridRequest } from "../src/hardened-bash.mjs";

test("removes canonical and resolver-selected secrets", () => {
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

test("does not mutate the Pi environment object", () => {
  const source = { PATH: "/bin", MINIMAX_API_KEY: "secret" };

  sanitizeEnvironment(source, ["MINIMAX_API_KEY"]);

  assert.equal(source.MINIMAX_API_KEY, "secret");
});

test("builds strict gridctl protocol requests", () => {
  assert.deepEqual(buildGridRequest("element.resolve", { query: "11" }, "req-1"), {
    protocol_version: "1.0",
    request_id: "req-1",
    operation: "element.resolve",
    arguments: { query: "11" },
  });
});
