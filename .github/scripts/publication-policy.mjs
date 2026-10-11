import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";

export const REPOSITORY = "slicedearth/breachgazette";
const SHA = /^[0-9a-f]{40}$/;

export function requireExpectedSource(revision, expectedSource = "", releaseId = "") {
  if ((releaseId && !SHA.test(expectedSource)) ||
      (expectedSource && (!SHA.test(expectedSource) || expectedSource !== revision))) {
    throw new Error("Publication source does not match the approved release revision.");
  }
}

export function requireTrustedPublication({ repository, revision, ref, event, branch, workflow, runs, triggerRun }) {
  if (
    repository !== REPOSITORY || !SHA.test(revision ?? "") ||
    ref !== "refs/heads/main" ||
    !["workflow_run", "workflow_dispatch", "schedule"].includes(event) ||
    branch?.name !== "main" || branch.protected !== true ||
    branch.commit?.sha !== revision ||
    workflow?.path !== ".github/workflows/ci.yml" || workflow.state !== "active" ||
    !Number.isSafeInteger(workflow.id) || !Array.isArray(runs)
  ) throw new Error("Publication requires the current protected main revision.");

  const trusted = runs.filter((run) =>
    Number.isSafeInteger(run.id) && run.workflow_id === workflow.id &&
    run.path === workflow.path && run.head_sha === revision &&
    run.event === "push" && run.head_branch === "main" &&
    run.repository?.full_name === repository &&
    run.head_repository?.full_name === repository
  ).sort((left, right) => right.id - left.id);
  const latest = trusted[0];
  if (!latest || latest.status !== "completed" || latest.conclusion !== "success" ||
      (event === "workflow_run" && latest.id !== Number(triggerRun))) {
    throw new Error("Publication requires the latest successful main-push CI run for this revision.");
  }
  return latest.id;
}

export function verifyPublication(env = process.env, api = (path) => JSON.parse(
  execFileSync("gh", ["api", path], { encoding: "utf8", timeout: 30_000, maxBuffer: 5_000_000 }),
), getRevision = () => execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim()) {
  const revision = getRevision();
  if (env.GITHUB_REPOSITORY !== REPOSITORY || !SHA.test(revision)) {
    throw new Error("Publication repository or source revision is invalid.");
  }
  requireExpectedSource(revision, env.PUBLICATION_EXPECTED_SOURCE, env.PUBLICATION_RELEASE_ID);
  const prefix = `repos/${REPOSITORY}`;
  const branch = api(`${prefix}/branches/main`);
  const workflow = api(`${prefix}/actions/workflows/ci.yml`);
  const result = api(`${prefix}/actions/workflows/ci.yml/runs?head_sha=${revision}&event=push&branch=main&per_page=100`);
  const run = requireTrustedPublication({
    repository: env.GITHUB_REPOSITORY, revision, ref: env.GITHUB_REF,
    event: env.GITHUB_EVENT_NAME, branch, workflow, runs: result.workflow_runs,
    triggerRun: env.PUBLICATION_TRIGGER_RUN,
  });
  console.log(`Protected main and successful CI verified: ${revision}, run ${run}.`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try { verifyPublication(); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
