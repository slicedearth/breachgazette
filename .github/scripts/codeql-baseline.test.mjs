import assert from "node:assert/strict";
import test from "node:test";
import { CONFIGURATIONS, reconcile } from "./codeql-baseline.mjs";

const ref = "refs/pull/42/merge";
const revision = "a".repeat(40);
const analyses = () => CONFIGURATIONS.map((configuration, index) => ({
  ...configuration, id: index + 1, ref, commit_sha: revision, error: "", tool: { name: "CodeQL" },
}));
test("both languages and both historical identities must be current", () => {
  assert.deepEqual(reconcile(analyses(), ref, revision).map((item) => item.status), Array(4).fill("current"));
  assert.equal(reconcile(analyses().slice(0, 2), ref, revision).filter((item) => item.status === "missing").length, 2);
});
for (const [name, mutate, status] of [
  ["stale revision", (a) => { a.commit_sha = "b".repeat(40); }, "stale"],
  ["processing error", (a) => { a.error = "synthetic error"; }, "failed"],
  ["wrong category", (a) => { a.category = "renamed"; }, "missing"],
  ["wrong invocation", (a) => { a.analysis_key = "other"; }, "missing"],
  ["wrong ref", (a) => { a.ref = "refs/heads/main"; }, "missing"],
  ["different tool", (a) => { a.tool.name = "Other"; }, "missing"],
]) {
  test(`rejects ${name}`, () => {
    const values = analyses(); mutate(values[0]);
    assert.equal(reconcile(values, ref, revision)[0].status, status);
  });
}
test("a newer failed analysis cannot be masked by an earlier success", () => {
  const values = analyses(); values.push({ ...values[0], id: 9, error: "failed" });
  assert.equal(reconcile(values, ref, revision)[0].status, "failed");
});
