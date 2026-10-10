import assert from "node:assert/strict";
import test from "node:test";
import { REPOSITORY, requireTrustedPublication } from "./publication-policy.mjs";

function evidence(event = "workflow_dispatch") {
  const revision = "a".repeat(40);
  return {
    repository: REPOSITORY, revision, ref: "refs/heads/main", event, triggerRun: "42",
    branch: { name: "main", protected: true, commit: { sha: revision } },
    workflow: { id: 7, path: ".github/workflows/ci.yml", state: "active" },
    runs: [{
      id: 42, workflow_id: 7, path: ".github/workflows/ci.yml", head_sha: revision,
      event: "push", head_branch: "main", status: "completed", conclusion: "success",
      repository: { full_name: REPOSITORY }, head_repository: { full_name: REPOSITORY },
    }],
  };
}

for (const event of ["workflow_dispatch", "workflow_run", "schedule"]) {
  test(`${event} accepts current protected main with trusted CI`, () => {
    assert.equal(requireTrustedPublication(evidence(event)), 42);
  });
}

const rejected = {
  "unprotected main": (e) => { e.branch.protected = false; },
  "stale main revision": (e) => { e.branch.commit.sha = "b".repeat(40); },
  "release tag": (e) => { e.ref = "refs/tags/v1"; },
  "feature branch dispatch": (e) => { e.ref = "refs/heads/feature"; },
  "fork repository": (e) => { e.repository = "fork/breachgazette"; },
  "PR-only CI": (e) => { e.runs[0].event = "pull_request"; },
  "wrong CI branch": (e) => { e.runs[0].head_branch = "feature"; },
  "fork CI head": (e) => { e.runs[0].head_repository.full_name = "fork/breachgazette"; },
  "wrong CI repository": (e) => { e.runs[0].repository.full_name = "other/repo"; },
  "wrong CI workflow": (e) => { e.runs[0].workflow_id = 8; },
  "wrong CI path": (e) => { e.runs[0].path = ".github/workflows/other.yml"; },
  "wrong CI revision": (e) => { e.runs[0].head_sha = "b".repeat(40); },
  "incomplete CI": (e) => { e.runs[0].status = "in_progress"; },
  "failed CI": (e) => { e.runs[0].conclusion = "failure"; },
  "disabled CI": (e) => { e.workflow.state = "disabled_manually"; },
  "missing CI evidence": (e) => { e.runs = []; },
  "superseded successful run": (e) => { e.runs.push({ ...e.runs[0], id: 43, conclusion: "failure" }); },
  "stale workflow-run event": (e) => { e.event = "workflow_run"; e.triggerRun = "41"; },
};
for (const [name, mutate] of Object.entries(rejected)) {
  test(`rejects ${name}`, () => {
    const value = evidence(); mutate(value);
    assert.throws(() => requireTrustedPublication(value), /Publication requires/);
  });
}
