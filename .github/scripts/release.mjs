import { execFileSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { closeSync, existsSync, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync, realpathSync, renameSync, rmdirSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import { REPOSITORY, requireTrustedPublication } from "./publication-policy.mjs";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const SHA = /^[0-9a-f]{40}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const STAGES = ["prepared", "pausing", "paused", "dispatching", "waiting", "verified", "complete"];
const PREFIX = `repos/${REPOSITORY}`;
const FLAG = "BREACHGAZETTE_SCHEDULE_ENABLED";
const ARTIFACT_LIMIT = 128 * 1024 * 1024;
const WORKFLOW_REF = `${REPOSITORY}/.github/workflows/netlify.yml@refs/heads/main`;

function requireValue(condition, message) {
  if (!condition) throw new Error(message);
}

export function validateReceipt(receipt, source, state) {
  requireValue(receipt?.version === 1 && UUID.test(receipt.id) &&
    receipt.source === source && SHA.test(source) && receipt.state === state && SHA.test(state) &&
    typeof receipt.wasEnabled === "boolean" && STAGES.includes(receipt.stage), "Receipt does not match this release.");
  if (STAGES.indexOf(receipt.stage) >= STAGES.indexOf("dispatching")) {
    requireValue(Number.isFinite(Date.parse(receipt.dispatchedAt)), "Receipt has no dispatch time.");
  }
  if (STAGES.indexOf(receipt.stage) >= STAGES.indexOf("waiting")) {
    requireValue(Number.isSafeInteger(receipt.runId) && receipt.runId > 0, "Receipt has no run identity.");
  }
  if (receipt.provenance) requireProvenance(receipt.provenance, receipt);
  if (STAGES.indexOf(receipt.stage) >= STAGES.indexOf("verified")) {
    requireProvenance(receipt.provenance, receipt);
    requireValue(receipt.checksum === receipt.provenance.checksum, "Receipt has no bound publication identity.");
  }
  return receipt;
}

export function requireRun(run, receipt, workflow) {
  requireValue(run?.workflow_id === workflow.id && run.path === workflow.path &&
    run.head_sha === receipt.source && run.head_branch === "main" &&
    run.event === "workflow_dispatch" && run.display_title === `Release ${receipt.id}` &&
    run.repository?.full_name === REPOSITORY && run.head_repository?.full_name === REPOSITORY &&
    run.run_attempt === 1 && Date.parse(run.created_at) >= Date.parse(receipt.dispatchedAt) - 5000,
  "Deployment run does not match the approved release.");
}

// One checkpoint per call makes interruption and uncertain dispatch outcomes recoverable.
// No failed checkpoint resumes collection, and a recorded dispatch is never repeated.
export async function advance(receipt, io) {
  const snapshot = await io.inspect();
  requireValue(snapshot.source === receipt.source && snapshot.state === receipt.state,
    "Production inputs changed. Stop and review a new release.");
  if (receipt.stage === "complete") return receipt;
  const save = (fields) => { io.save({ ...receipt, ...fields }); Object.assign(receipt, fields); return receipt; };
  const stable = async () => {
    const current = await io.inspect();
    requireValue(current.source === receipt.source && current.state === receipt.state &&
      current.enabled === snapshot.enabled && !current.busy, "Release inputs or activity changed during verification.");
  };
  if (receipt.stage === "prepared") {
    requireValue(snapshot.enabled === receipt.wasEnabled, "Schedule setting changed after preparation.");
    requireValue(!snapshot.busy, "An update or publication is running. Wait for it to finish.");
    await io.preflight();
    await stable();
    return save({ stage: "pausing" });
  }
  if (receipt.stage === "pausing") {
    requireValue(!snapshot.enabled || receipt.wasEnabled, "Schedule setting changed after preparation.");
    // Intent is already durable: retrying this pause is safe after a lost response.
    await io.setEnabled(false);
    return save({ stage: "paused" });
  }
  if (receipt.stage !== "verified") {
    requireValue(!snapshot.enabled, "Collection must remain paused until this release is verified.");
  }
  if (receipt.stage === "paused") {
    requireValue(!snapshot.busy, "An update or publication is draining. Leave collection paused.");
    await io.preflight();
    await stable();
    save({ stage: "dispatching", dispatchedAt: io.now() });
    await io.dispatch(receipt.id, receipt.source, receipt.state);
    return receipt;
  }
  if (receipt.stage === "dispatching") {
    const matches = (await io.runs()).filter((run) => run.display_title === `Release ${receipt.id}`);
    requireValue(matches.length <= 1, "Multiple runs match this release. Manual review is required.");
    if (!matches.length) return receipt;
    requireRun(matches[0], receipt, snapshot.workflow);
    return save({ stage: "waiting", runId: matches[0].id });
  }
  const run = await io.run(receipt.runId);
  requireRun(run, receipt, snapshot.workflow);
  if (run.status !== "completed") return receipt;
  requireValue(run.conclusion === "success", "Deployment failed. Collection remains paused; inspect the run before starting a new release.");
  const provenance = await io.provenance(run, receipt);
  requireProvenance(provenance, receipt);
  if (receipt.provenance) {
    requireValue(JSON.stringify(provenance) === JSON.stringify(receipt.provenance), "Recorded deployment provenance changed.");
  } else {
    // Save expected evidence before contacting the endpoint under verification.
    save({ provenance });
  }
  const identity = await io.verifyLive(receipt.source, provenance.checksum);
  requireValue(identity.checksum === provenance.checksum, "Live publication changed from the recorded deployment.");
  if (receipt.stage === "waiting") return save({ stage: "verified", checksum: provenance.checksum });
  requireValue(receipt.checksum === provenance.checksum, "Receipt publication identity changed.");
  requireValue(!snapshot.enabled || receipt.wasEnabled, "Schedule setting changed before restoration.");
  requireValue(!snapshot.busy, "Another update or publication is running. Do not resume collection yet.");
  await stable();
  if (snapshot.enabled !== receipt.wasEnabled) await io.setEnabled(receipt.wasEnabled);
  return save({ stage: "complete" });
}

function command(program, args, options = {}) {
  try {
    const result = execFileSync(program, args, { cwd: ROOT, encoding: "utf8", timeout: 60_000,
      maxBuffer: 8_000_000, stdio: ["pipe", "pipe", "pipe"], ...options });
    return typeof result === "string" ? result.trim() : result;
  } catch {
    // Child diagnostics may contain private paths, records or credential-bearing URLs.
    throw new Error("A required command failed. Review it privately; no automatic recovery was attempted.");
  }
}

export function api(path, body, method, run = command) {
  const args = ["api", path];
  if (method) args.push("--method", method);
  if (body) args.push("--input", "-");
  const result = run("gh", args, body ? { input: JSON.stringify(body) } : {});
  return result ? JSON.parse(result) : null;
}

export function dispatchRelease(id, source, state, request = api) {
  requireValue(UUID.test(id) && SHA.test(source) && SHA.test(state), "Invalid release dispatch inputs.");
  return request(`${PREFIX}/actions/workflows/netlify.yml/dispatches`,
    { ref: "main", inputs: { expected_source: source, data_ref: state, release_id: id } }, "POST");
}

export function requireProvenance(evidence, receipt) {
  requireValue(evidence?.version === "1.1" && evidence.runId === receipt.runId && evidence.runAttempt === 1 &&
    evidence.source === receipt.source && evidence.state === receipt.state && evidence.workflowRef === WORKFLOW_REF &&
    Number.isSafeInteger(evidence.artifactId) && evidence.artifactId > 0 &&
    /^sha256:[0-9a-f]{64}$/.test(evidence.artifactDigest) && DIGEST.test(evidence.archiveSha256) &&
    DIGEST.test(evidence.checksum), "Deployment provenance does not match the approved release.");
}

export function readProvenanceArchive(bytes) {
  return JSON.parse(command(join(ROOT, ".venv/bin/python"),
    [join(ROOT, ".github/scripts/read_provenance.py")], { input: bytes }));
}

export async function readRunProvenance(run, receipt, {
  request = api,
  download = (id) => command("gh", ["api", `${PREFIX}/actions/artifacts/${id}/zip`],
    { encoding: null, maxBuffer: ARTIFACT_LIMIT }),
  readArchive = readProvenanceArchive,
} = {}) {
  requireValue(run.id === receipt.runId && run.run_attempt === 1 && run.head_sha === receipt.source &&
    run.status === "completed" && run.conclusion === "success", "Provenance requires the recorded successful run.");
  const name = `deployment-${receipt.source}`;
  const inventory = await request(`${PREFIX}/actions/runs/${receipt.runId}/artifacts?name=${name}&per_page=100`);
  requireValue(Array.isArray(inventory?.artifacts) && inventory.total_count === inventory.artifacts.length,
    "Deployment provenance inventory is unavailable or incomplete.");
  const matches = inventory.artifacts.filter((artifact) => artifact.name === name);
  requireValue(matches.length === 1, "Exactly one deployment provenance artifact is required.");
  const artifact = matches[0];
  requireValue(Number.isSafeInteger(artifact.id) && artifact.id > 0 && artifact.expired === false &&
    Number.isFinite(Date.parse(artifact.expires_at)) && Date.parse(artifact.expires_at) > Date.now() &&
    Number.isSafeInteger(artifact.size_in_bytes) && artifact.size_in_bytes > 0 && artifact.size_in_bytes <= ARTIFACT_LIMIT &&
    /^sha256:[0-9a-f]{64}$/.test(artifact.digest) && artifact.workflow_run?.id === receipt.runId &&
    artifact.workflow_run.head_sha === receipt.source && artifact.workflow_run.head_branch === "main",
  "Deployment provenance artifact is expired, invalid or belongs to another run.");
  if (receipt.provenance) {
    requireProvenance(receipt.provenance, receipt);
    requireValue(receipt.provenance.artifactId === artifact.id && receipt.provenance.artifactDigest === artifact.digest,
      "Recorded deployment provenance artifact changed.");
    return receipt.provenance;
  }
  const bytes = await download(artifact.id);
  requireValue(Buffer.isBuffer(bytes) && bytes.length <= ARTIFACT_LIMIT &&
    `sha256:${createHash("sha256").update(bytes).digest("hex")}` === artifact.digest,
  "Deployment provenance artifact digest does not match.");
  const record = await readArchive(bytes);
  requireValue(record?.schema_version === "1.1" && record.workflow?.run_id === String(receipt.runId) &&
    record.workflow.run_attempt === "1" && record.workflow.ref === WORKFLOW_REF &&
    record.source_revision === receipt.source && record.data_revision === receipt.state &&
    record.subject?.name === "breachgazette-site.zip" && record.assurance?.signed === false,
  "Deployment provenance record does not match the approved release.");
  const evidence = { version: record.schema_version, runId: receipt.runId, runAttempt: 1,
    source: record.source_revision, state: record.data_revision, workflowRef: record.workflow.ref,
    artifactId: artifact.id, artifactDigest: artifact.digest, archiveSha256: record.subject.sha256,
    checksum: record.publication_checksum };
  requireProvenance(evidence, receipt);
  return evidence;
}

export function receiptPath(value) {
  requireValue(isAbsolute(value), "Use an absolute receipt path outside all repositories.");
  const path = resolve(value);
  const parent = dirname(path);
  requireValue(realpathSync(parent) === parent, "Receipt directory must not contain symbolic links.");
  const info = lstatSync(parent);
  requireValue(info.isDirectory() && (info.mode & 0o077) === 0 && info.uid === process.getuid(),
    "Receipt directory must be owner-only (mode 700).");
  for (let folder = parent; ; folder = dirname(folder)) {
    requireValue(!existsSync(join(folder, ".git")), "Receipts must remain outside repositories.");
    if (folder === dirname(folder)) break;
  }
  if (existsSync(path)) {
    const stat = lstatSync(path);
    requireValue(stat.isFile() && !stat.isSymbolicLink() && stat.size <= 4096 &&
      (stat.mode & 0o077) === 0 && stat.uid === process.getuid(), "Receipt must be a bounded owner-only regular file.");
  }
  return path;
}

export function saveReceipt(path, receipt, fs = { openSync, writeFileSync, fsyncSync, closeSync, renameSync }) {
  receiptPath(path);
  const contents = `${JSON.stringify(receipt, null, 2)}\n`;
  requireValue(Buffer.byteLength(contents) <= 4096, "Receipt exceeds its size limit.");
  const temporary = `${path}.${randomUUID()}.tmp`;
  let file;
  let directory;
  try {
    file = fs.openSync(temporary, "wx", 0o600);
    fs.writeFileSync(file, contents);
    fs.fsyncSync(file);
    fs.closeSync(file); file = undefined;
    fs.renameSync(temporary, path);
    directory = fs.openSync(dirname(path), "r");
    fs.fsyncSync(directory);
  } finally {
    if (file !== undefined) fs.closeSync(file);
    if (directory !== undefined) fs.closeSync(directory);
    if (existsSync(temporary)) unlinkSync(temporary);
  }
}

async function response(url) {
  const result = await fetch(url, { redirect: "error", signal: AbortSignal.timeout(30_000),
    headers: { "Cache-Control": "no-cache" } });
  requireValue(result.ok, "A live publication request failed.");
  const chunks = [];
  let size = 0;
  for await (const chunk of result.body) {
    size += chunk.length;
    requireValue(size <= 2_000_000, "A live verification response exceeded its size limit.");
    chunks.push(chunk);
  }
  return { bytes: Buffer.concat(chunks), headers: result.headers };
}

export async function verifyLive(origin, source, checksum, get = response) {
  requireValue(DIGEST.test(checksum), "An expected publication checksum is required.");
  requireValue(/^https:\/\/[a-z0-9.-]+\/?$/.test(origin), "Production origin must be HTTPS without a path.");
  origin = origin.replace(/\/$/, "");
  const identity = JSON.parse((await get(`${origin}/data/publication.json?publication=${checksum}`)).bytes);
  requireValue(identity.source_revision === source && identity.publication_checksum === checksum &&
    Number.isSafeInteger(identity.record_counts?.notifications) && identity.record_counts.notifications > 0,
  "Live publication does not match the release.");
  const { bytes } = await get(`${origin}/data/notifications/manifest.json`);
  requireValue(identity.search_manifest_binding?.schema_version === "1.0" &&
    createHash("sha256").update(bytes).digest("hex") === identity.search_manifest_binding.sha256 &&
    JSON.parse(bytes).record_count === identity.record_counts.notifications, "Live search manifest does not match its publication.");
  const { headers } = await get(`${origin}/`);
  for (const [name, value] of Object.entries({
    "content-security-policy": "frame-ancestors 'none'", "strict-transport-security": "max-age=31536000",
    "x-content-type-options": "nosniff", "x-frame-options": "DENY", "referrer-policy": "no-referrer",
    "cross-origin-opener-policy": "same-origin",
  })) requireValue(headers.get(name)?.toLowerCase().includes(value.toLowerCase()), "A required live security header is missing.");
  requireValue(Boolean(headers.get("permissions-policy")), "A required live security header is missing.");
  return { checksum: identity.publication_checksum };
}

function runtime(source, state, dataRoot, path) {
  let origin;
  let privateRepository;
  const variable = (name) => api(`${PREFIX}/actions/variables/${name}`).value;
  return {
    async inspect() {
      requireValue(command("git", ["rev-parse", "HEAD"]) === source &&
        command("git", ["status", "--porcelain"]) === "", "Use a clean checkout at the approved source revision.");
      const branch = api(`${PREFIX}/branches/main`);
      const ci = api(`${PREFIX}/actions/workflows/ci.yml`);
      const runs = api(`${PREFIX}/actions/workflows/ci.yml/runs?head_sha=${source}&event=push&branch=main&per_page=100`);
      requireTrustedPublication({ repository: REPOSITORY, revision: source, ref: "refs/heads/main",
        event: "workflow_dispatch", branch, workflow: ci, runs: runs.workflow_runs });
      privateRepository = variable("BREACHGAZETTE_DATA_REPOSITORY");
      requireValue(/^slicedearth\/[a-z0-9._-]+$/.test(privateRepository) && privateRepository !== REPOSITORY &&
        variable("BREACHGAZETTE_DATA_REF") === "main", "Expected a separate private state repository on main.");
      requireValue(api(`repos/${privateRepository}`).private === true, "State repository must be private.");
      const currentState = api(`repos/${privateRepository}/git/ref/heads/main`).object.sha;
      const enabled = variable(FLAG);
      requireValue(["true", "false"].includes(enabled), "Schedule flag must be explicitly true or false.");
      origin = variable("BREACHGAZETTE_SITE_URL");
      const workflow = api(`${PREFIX}/actions/workflows/netlify.yml`);
      requireValue(workflow.state === "active" && workflow.path === ".github/workflows/netlify.yml" &&
        Number.isSafeInteger(workflow.id), "Publication workflow must be active.");
      const active = ["queued", "in_progress", "waiting", "pending", "requested"]
        .flatMap((status) => {
          const result = api(`${PREFIX}/actions/runs?status=${status}&per_page=100`);
          requireValue(Array.isArray(result.workflow_runs) && result.total_count <= result.workflow_runs.length,
            "Active-run inventory is incomplete. Review Actions before releasing.");
          return result.workflow_runs;
        });
      const busy = active.some((run) => [".github/workflows/netlify.yml", ".github/workflows/scheduled-private-update.yml"].includes(run.path));
      return { source: branch.commit.sha, state: currentState, enabled: enabled === "true", workflow, busy };
    },
    async preflight() {
      const root = realpathSync(dataRoot);
      const inside = relative(ROOT, root);
      requireValue((inside === ".." || inside.startsWith("../")) && root !== dirname(ROOT), "Private state must be outside the source checkout.");
      const git = (args) => command("git", ["-C", root, ...args]);
      requireValue(git(["rev-parse", "--show-toplevel"]) === root && git(["rev-parse", "HEAD"]) === state &&
        git(["status", "--porcelain"]) === "", "Private checkout must be clean at the approved state revision.");
      const remote = git(["remote", "get-url", "origin"]);
      requireValue([`https://github.com/${privateRepository}.git`, `git@github.com:${privateRepository}.git`].includes(remote),
        "Private checkout origin does not match the configured repository.");
      const report = JSON.parse(command(join(ROOT, ".venv/bin/python"),
        ["-m", "breachgazette.cli", "deployment-preflight", "--data-root", root, "--json"],
        { timeout: 120_000, env: { ...process.env, PYTHONPATH: join(ROOT, "src") } }));
      requireValue(report.passed === true && Object.keys(report.checks ?? {}).length === 9 &&
        Object.values(report.checks).every((value) => value === true), "Offline state compatibility or publication gate failed.");
    },
    setEnabled: async (enabled) => api(`${PREFIX}/actions/variables/${FLAG}`, { name: FLAG, value: String(enabled) }, "PATCH"),
    dispatch: dispatchRelease,
    runs: async () => api(`${PREFIX}/actions/workflows/netlify.yml/runs?event=workflow_dispatch&per_page=100`).workflow_runs,
    run: async (id) => api(`${PREFIX}/actions/runs/${id}`),
    provenance: readRunProvenance,
    verifyLive: (revision, checksum) => verifyLive(origin, revision, checksum),
    now: () => new Date().toISOString(),
    save: (receipt) => saveReceipt(path, receipt),
  };
}

async function main() {
  const { values } = parseArgs({ options: { source: { type: "string" }, state: { type: "string" },
    "data-root": { type: "string" }, receipt: { type: "string" }, apply: { type: "boolean", default: false },
    help: { type: "boolean", default: false } }, allowPositionals: false });
  if (values.help) {
    console.log("node .github/scripts/release.mjs --source SHA --state SHA --data-root /private/checkout --receipt /private/receipts/release.json [--apply]\nWithout --apply: read-only readiness checks. With --apply: pause collection, publish exact inputs, verify, restore the prior schedule setting. Reuse the same receipt to resume. Never migrates, commits, pushes or merges.");
    return;
  }
  requireValue(SHA.test(values.source ?? "") && SHA.test(values.state ?? "") && isAbsolute(values["data-root"] ?? ""),
    "Provide exact source/state SHAs and an absolute private checkout path.");
  const path = receiptPath(values.receipt ?? "");
  const io = runtime(values.source, values.state, values["data-root"], path);
  const snapshot = await io.inspect();
  requireValue(snapshot.state === values.state, "Private main has advanced beyond the approved state revision.");
  if (!values.apply) {
    await io.preflight();
    console.log(JSON.stringify({ ready: !snapshot.busy, source: values.source, state: values.state,
      collection_enabled: snapshot.enabled, remote_changes: false }));
    return;
  }
  const lock = `${path}.lock`;
  mkdirSync(lock, { mode: 0o700 });
  try {
    const receipt = existsSync(path) ? validateReceipt(JSON.parse(readFileSync(path, "utf8")), values.source, values.state)
      : { version: 1, id: randomUUID(), source: values.source, state: values.state, wasEnabled: snapshot.enabled, stage: "prepared" };
    io.save(receipt);
    const deadline = Date.now() + 30 * 60_000;
    while (Date.now() < deadline) {
      const stage = receipt.stage;
      await advance(receipt, io);
      console.log(`Release checkpoint: ${receipt.stage}${receipt.runId ? ` (run ${receipt.runId})` : ""}.`);
      if (receipt.stage === "complete") return;
      if (receipt.stage === stage) await new Promise((resolveWait) => setTimeout(resolveWait, 10_000));
    }
    throw new Error("Release is still pending. Reuse this receipt to resume; collection remains paused. An uncertain dispatch is never repeated automatically.");
  } finally { rmdirSync(lock); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => { console.error(error.message); process.exitCode = 1; });
}
