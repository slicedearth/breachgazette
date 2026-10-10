import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { chmodSync, mkdtempSync, readFileSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";
import { advance, receiptPath, requireRun, saveReceipt, validateReceipt, verifyLive } from "./release.mjs";
import { REPOSITORY } from "./publication-policy.mjs";

function harness(wasEnabled = true) {
  const receipt = { version: 1, id: "12345678-1234-4123-8123-123456789abc", source: "a".repeat(40),
    state: "b".repeat(40), stage: "prepared", wasEnabled };
  const workflow = { id: 7, path: ".github/workflows/netlify.yml" };
  const snapshot = { source: receipt.source, state: receipt.state, enabled: wasEnabled, workflow, busy: false };
  const run = { id: 42, workflow_id: 7, path: workflow.path, head_sha: receipt.source, head_branch: "main",
    event: "workflow_dispatch", display_title: `Release ${receipt.id}`, run_attempt: 1,
    created_at: "2026-01-01T00:00:00Z", repository: { full_name: REPOSITORY }, head_repository: { full_name: REPOSITORY },
    status: "completed", conclusion: "success" };
  const writes = [];
  const saved = [];
  const io = { inspect: async () => ({ ...snapshot }), preflight: async () => {},
    save: (r) => saved.push(structuredClone(r)),
    setEnabled: async (enabled) => { writes.push(["flag", enabled]); snapshot.enabled = enabled; },
    dispatch: async (...args) => writes.push(["dispatch", ...args]),
    runs: async () => [run], run: async () => run, verifyLive: async () => ({ checksum: "c".repeat(64) }),
    now: () => "2026-01-01T00:00:00Z" };
  return { receipt, snapshot, run, io, writes, saved };
}

async function reach(h, stage) {
  for (let i = 0; h.receipt.stage !== stage && i < 10; i++) await advance(h.receipt, h.io);
  assert.equal(h.receipt.stage, stage);
}

for (const enabled of [true, false]) test(`complete release restores prior setting ${enabled}`, async () => {
  const h = harness(enabled);
  await reach(h, "complete");
  assert.equal(h.snapshot.enabled, enabled);
  assert.equal(h.writes.filter(([action]) => action === "dispatch").length, 1);
  assert.equal(validateReceipt(h.receipt, h.receipt.source, h.receipt.state), h.receipt);
  const writes = h.writes.length;
  await advance(h.receipt, h.io);
  assert.equal(h.writes.length, writes);
});

for (const changed of ["source", "state"]) test(`changed ${changed} stops before writes`, async () => {
  const h = harness(); h.snapshot[changed] = "d".repeat(40);
  await assert.rejects(advance(h.receipt, h.io), /inputs changed/);
  assert.deepEqual(h.writes, []);
});

test("preflight failure cannot pause, dispatch or resume", async () => {
  const h = harness(); h.io.preflight = async () => { throw new Error("preflight"); };
  await assert.rejects(advance(h.receipt, h.io), /preflight/);
  assert.deepEqual(h.writes, []);
});

test("state movement during preflight stops before pausing", async () => {
  const h = harness(); h.io.preflight = async () => { h.snapshot.state = "d".repeat(40); };
  await assert.rejects(advance(h.receipt, h.io), /changed during/);
  assert.deepEqual(h.writes, []);
});

test("in-flight workflow blocks release, including after pause", async () => {
  const h = harness(); h.snapshot.busy = true;
  await assert.rejects(advance(h.receipt, h.io), /running/);
  h.snapshot.busy = false; await reach(h, "paused"); h.snapshot.busy = true;
  await assert.rejects(advance(h.receipt, h.io), /draining/);
  assert.deepEqual(h.writes, [["flag", false]]);
});

test("lost pause response resumes safely from durable intent", async () => {
  const h = harness(); await reach(h, "pausing");
  const set = h.io.setEnabled;
  h.io.setEnabled = async (value) => { await set(value); throw new Error("lost response"); };
  await assert.rejects(advance(h.receipt, h.io), /lost response/);
  assert.equal(h.receipt.stage, "pausing");
  h.io.setEnabled = set; await reach(h, "complete");
});

test("uncertain dispatch is not duplicated, including when no run is visible", async () => {
  const h = harness(); await reach(h, "paused");
  h.io.dispatch = async () => { h.writes.push(["dispatch"]); throw new Error("lost response"); };
  await assert.rejects(advance(h.receipt, h.io), /lost response/);
  assert.equal(h.saved.at(-1).stage, "dispatching");
  h.io.runs = async () => []; await advance(h.receipt, h.io);
  assert.equal(h.receipt.stage, "dispatching");
  h.io.runs = async () => [h.run]; await reach(h, "complete");
  assert.equal(h.writes.filter(([action]) => action === "dispatch").length, 1);
});

test("duplicate correlated runs require manual review", async () => {
  const h = harness(); await reach(h, "dispatching"); h.io.runs = async () => [h.run, h.run];
  await assert.rejects(advance(h.receipt, h.io), /Multiple runs/);
  assert.equal(h.snapshot.enabled, false);
});

for (const conclusion of ["failure", "cancelled", "skipped", "timed_out"]) test(`${conclusion} leaves collection paused`, async () => {
  const h = harness(); await reach(h, "waiting"); h.run.conclusion = conclusion;
  await assert.rejects(advance(h.receipt, h.io), /Deployment failed/);
  assert.equal(h.snapshot.enabled, false);
});

test("pending run waits and live verification failure never resumes collection", async () => {
  const h = harness(); await reach(h, "waiting"); h.run.status = "in_progress";
  await advance(h.receipt, h.io); assert.equal(h.receipt.stage, "waiting");
  h.run.status = "completed"; h.io.verifyLive = async () => { throw new Error("live mismatch"); };
  await assert.rejects(advance(h.receipt, h.io), /live mismatch/);
  assert.equal(h.snapshot.enabled, false);
});

test("live identity changes and unexpected schedule enablement block restoration", async () => {
  const h = harness(); await reach(h, "verified");
  h.io.verifyLive = async () => ({ checksum: "d".repeat(64) });
  await assert.rejects(advance(h.receipt, h.io), /publication changed/);
  const paused = harness(false); await reach(paused, "verified"); paused.snapshot.enabled = true;
  await assert.rejects(advance(paused.receipt, paused.io), /setting changed/);
});

test("lost restoration response resumes without another deployment", async () => {
  const h = harness(); await reach(h, "verified"); h.snapshot.enabled = true;
  await reach(h, "complete");
  assert.equal(h.writes.filter(([action]) => action === "dispatch").length, 1);
});

for (const [field, value] of Object.entries({ head_sha: "d".repeat(40), head_branch: "feature", run_attempt: 2,
  event: "push", workflow_id: 8, path: "wrong.yml", display_title: "other", created_at: "2025-01-01T00:00:00Z",
  repository: { full_name: "fork/repo" }, head_repository: { full_name: "fork/repo" } })) {
  test(`rejects wrong deployment ${field}`, () => {
    const h = harness(); h.receipt.dispatchedAt = h.io.now(); h.run[field] = value;
    assert.throws(() => requireRun(h.run, h.receipt, h.snapshot.workflow), /does not match/);
  });
}

test("receipts bind exact inputs and required checkpoints", async () => {
  const h = harness(); await reach(h, "complete");
  for (const [field, value] of Object.entries({ source: "x", state: "x", stage: "unknown", id: "../wrong",
    runId: "42", checksum: "wrong", dispatchedAt: "wrong", version: 2, wasEnabled: "true" })) {
    assert.throws(() => validateReceipt({ ...h.receipt, [field]: value }, h.receipt.source, h.receipt.state));
  }
});

test("receipt storage is owner-only and rejects public, symlinked and oversized files", () => {
  const directory = mkdtempSync(join(realTmp(), "breachgazette-receipt-test-"));
  chmodSync(directory, 0o700);
  const path = join(directory, "release.json");
  saveReceipt(path, harness().receipt);
  assert.equal(statSync(path).mode & 0o777, 0o600);
  assert.equal(JSON.parse(readFileSync(path, "utf8")).stage, "prepared");
  const link = join(directory, "alias.json"); symlinkSync(path, link);
  assert.throws(() => receiptPath(link));
  writeFileSync(path, "x".repeat(4097)); assert.throws(() => receiptPath(path));
  chmodSync(directory, 0o755); assert.throws(() => receiptPath(path));
  assert.throws(() => receiptPath(resolve("release.json")));
});

function realTmp() { return process.platform === "darwin" ? "/private/tmp" : tmpdir(); }

function liveFixture() {
  const source = "a".repeat(40);
  const manifest = Buffer.from(JSON.stringify({ record_count: 3 }));
  const identity = { source_revision: source, publication_checksum: "c".repeat(64), record_counts: { notifications: 3 },
    search_manifest_binding: { schema_version: "1.0", sha256: createHash("sha256").update(manifest).digest("hex") } };
  const headers = new Headers({ "content-security-policy": "default-src 'self'; frame-ancestors 'none'",
    "strict-transport-security": "max-age=31536000", "x-content-type-options": "nosniff", "x-frame-options": "DENY",
    "referrer-policy": "no-referrer", "cross-origin-opener-policy": "same-origin", "permissions-policy": "camera=()" });
  return { source, identity, headers, get: async (url) => ({ headers, bytes: url.includes("publication.json")
    ? Buffer.from(JSON.stringify(identity)) : url.includes("manifest.json") ? manifest : Buffer.from("<html>") }) };
}

test("live verifier binds source, nonempty counts, exact search bytes and security headers", async () => {
  const f = liveFixture();
  assert.deepEqual(await verifyLive("https://breachgazette.example", f.source, f.get), { checksum: "c".repeat(64) });
  f.identity.source_revision = "b".repeat(40);
  await assert.rejects(verifyLive("https://breachgazette.example", f.source, f.get), /does not match/);
});

for (const failure of ["count", "digest", "binding", "header", "origin"]) test(`live ${failure} mismatch fails closed`, async () => {
  const f = liveFixture();
  if (failure === "count") f.identity.record_counts.notifications = 0;
  if (failure === "digest") f.identity.search_manifest_binding.sha256 = "d".repeat(64);
  if (failure === "binding") f.identity.search_manifest_binding.schema_version = "0";
  if (failure === "header") f.headers.delete("referrer-policy");
  await assert.rejects(verifyLive(failure === "origin" ? "http://localhost" : "https://breachgazette.example", f.source, f.get));
});
