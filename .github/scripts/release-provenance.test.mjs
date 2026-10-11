import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import { readRunProvenance } from "./release.mjs";
import { REPOSITORY } from "./publication-policy.mjs";

function fixture() {
  const receipt = { source: "a".repeat(40), state: "b".repeat(40), runId: 42 };
  const run = { id: 42, run_attempt: 1, head_sha: receipt.source, status: "completed", conclusion: "success" };
  const bytes = Buffer.from("bounded archive fixture");
  const artifact = { id: 73, name: `deployment-${receipt.source}`, expired: false, expires_at: "9999-01-01T00:00:00Z",
    size_in_bytes: bytes.length, digest: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
    workflow_run: { id: 42, head_sha: receipt.source, head_branch: "main" } };
  const record = { schema_version: "1.1", source_revision: receipt.source, data_revision: receipt.state,
    publication_checksum: "c".repeat(64), subject: { name: "breachgazette-site.zip", sha256: "d".repeat(64) },
    workflow: { ref: `${REPOSITORY}/.github/workflows/netlify.yml@refs/heads/main`, run_id: "42", run_attempt: "1" },
    assurance: { signed: false } };
  const inventory = { total_count: 1, artifacts: [artifact] };
  const calls = [];
  const io = {
    request: async (path) => { calls.push(["metadata", path]); return inventory; },
    download: async (id) => { calls.push(["download", id]); return bytes; },
    readArchive: (value) => { assert.deepEqual(value, bytes); calls.push(["parse"]); return record; },
  };
  return { receipt, run, artifact, record, inventory, calls, io };
}

test("provenance adapter reads only the recorded run artifact and revalidates retained evidence", async () => {
  const f = fixture();
  const evidence = await readRunProvenance(f.run, f.receipt, f.io);
  assert.equal(evidence.checksum, f.record.publication_checksum);
  assert.equal(evidence.state, f.receipt.state);
  assert.deepEqual(f.calls, [["metadata", `repos/${REPOSITORY}/actions/runs/42/artifacts?name=deployment-${f.receipt.source}&per_page=100`],
    ["download", 73], ["parse"]]);
  f.receipt.provenance = JSON.parse(JSON.stringify(evidence));
  f.calls.length = 0;
  assert.deepEqual(await readRunProvenance(f.run, f.receipt, f.io), evidence);
  assert.equal(f.calls.length, 1, "retained evidence still requires available, unchanged artifact metadata");
  f.artifact.expired = true;
  await assert.rejects(readRunProvenance(f.run, f.receipt, f.io), /expired/);
});

const invalid = {
  "wrong run": f => { f.record.workflow.run_id = "43"; },
  "wrong attempt": f => { f.record.workflow.run_attempt = "2"; },
  "wrong source": f => { f.record.source_revision = "e".repeat(40); },
  "wrong state": f => { f.record.data_revision = "e".repeat(40); },
  "wrong workflow": f => { f.record.workflow.ref = "other"; },
  "old schema": f => { f.record.schema_version = "1.0"; },
  "missing checksum": f => { delete f.record.publication_checksum; },
  "malformed checksum": f => { f.record.publication_checksum = "wrong"; },
  "wrong archive subject": f => { f.record.subject.name = "other.zip"; },
  "malformed archive digest": f => { f.record.subject.sha256 = "wrong"; },
  "missing artifact": f => { f.inventory.artifacts = []; f.inventory.total_count = 0; },
  "duplicate artifacts": f => { f.inventory.artifacts.push({ ...f.artifact, id: 74 }); f.inventory.total_count = 2; },
  "incomplete inventory": f => { f.inventory.total_count = 101; },
  "expired artifact": f => { f.artifact.expired = true; },
  "past expiry": f => { f.artifact.expires_at = "2000-01-01T00:00:00Z"; },
  "oversized archive": f => { f.artifact.size_in_bytes = 128 * 1024 * 1024 + 1; },
  "artifact from another run": f => { f.artifact.workflow_run.id = 43; },
  "artifact from another source": f => { f.artifact.workflow_run.head_sha = "e".repeat(40); },
  "missing artifact digest": f => { delete f.artifact.digest; },
  "changed archive bytes": f => { f.io.download = async () => Buffer.from("changed"); },
  "unavailable metadata": f => { f.io.request = async () => { throw new Error("unavailable"); }; },
  "unavailable archive": f => { f.io.download = async () => { throw new Error("unavailable"); }; },
  "malformed JSON": f => { f.io.readArchive = () => JSON.parse("{"); },
};
for (const [name, mutate] of Object.entries(invalid)) test(`${name} rejects recorded-run provenance`, async () => {
  const f = fixture(); mutate(f);
  const before = structuredClone(f.receipt);
  await assert.rejects(readRunProvenance(f.run, f.receipt, f.io));
  assert.deepEqual(f.receipt, before, "the adapter never rewrites a failed receipt");
});

test("a changed artifact cannot replace checksum evidence already retained in the receipt", async () => {
  const f = fixture(); f.receipt.provenance = await readRunProvenance(f.run, f.receipt, f.io);
  const before = structuredClone(f.receipt);
  f.artifact.digest = `sha256:${"e".repeat(64)}`;
  await assert.rejects(readRunProvenance(f.run, f.receipt, f.io), /artifact changed/);
  assert.deepEqual(f.receipt, before);
});
