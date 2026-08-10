import test from "node:test";
import assert from "node:assert/strict";
import packageJson from "../package.json" with { type: "json" };

test("package pins the validated Pi API", () => {
  assert.equal(packageJson.dependencies["@earendil-works/pi-coding-agent"], "0.80.6");
});
