import assert from "node:assert/strict";
import test from "node:test";
import { REPOSITORY, requireExpectedSource, requireTrustedPublication, verifyPublication } from "./publication-policy.mjs";
import { api as requestApi, dispatchRelease } from "./release.mjs";

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

test("dispatch adapter carries approved source and rejects a later main with successful CI", () => {
  const approved = evidence();
  const later = evidence();
  later.revision = later.branch.commit.sha = later.runs[0].head_sha = "b".repeat(40);
  assert.equal(requireTrustedPublication(later), 42);
  let payload;
  dispatchRelease("12345678-1234-4123-8123-123456789abc", approved.revision, "c".repeat(40),
    (path, body, method) => {
      assert.equal(path, `repos/${REPOSITORY}/actions/workflows/netlify.yml/dispatches`);
      assert.equal(method, "POST");
      requestApi(path, body, method, (program, args, options) => {
        assert.equal(program, "gh");
        assert.deepEqual(args, ["api", path, "--method", "POST", "--input", "-"]);
        payload = JSON.parse(options.input);
        return "";
      });
    });
  assert.deepEqual(payload, { ref: "main", inputs: { expected_source: approved.revision,
    data_ref: "c".repeat(40), release_id: "12345678-1234-4123-8123-123456789abc" } });
  const env = { GITHUB_REPOSITORY: REPOSITORY, GITHUB_REF: "refs/heads/main", GITHUB_EVENT_NAME: "workflow_dispatch",
    PUBLICATION_EXPECTED_SOURCE: payload.inputs.expected_source, PUBLICATION_RELEASE_ID: payload.inputs.release_id };
  let reads = 0;
  const api = (path) => {
    reads++;
    if (path.endsWith("branches/main")) return later.branch;
    if (path.endsWith("workflows/ci.yml")) return later.workflow;
    if (path.includes("/runs?")) return { workflow_runs: later.runs };
    assert.fail("Unexpected API access");
  };
  assert.throws(() => verifyPublication(env, api, () => later.revision), /approved release revision/);
  assert.equal(reads, 0, "source binding fails before any API access");
  later.revision = later.branch.commit.sha = later.runs[0].head_sha = approved.revision;
  assert.doesNotThrow(() => verifyPublication(env, api, () => later.revision));
  assert.equal(reads, 3, "matching source must still pass the existing main and CI gates");
  later.runs[0].conclusion = "failure";
  assert.throws(() => verifyPublication(env, api, () => later.revision), /latest successful/);
});

test("correlated releases require an exact source while ordinary manual calls remain compatible", () => {
  for (const source of ["", "main", "a".repeat(39), "b".repeat(40)]) {
    assert.throws(() => requireExpectedSource("a".repeat(40), source, "release-id"), /approved release/);
  }
  assert.doesNotThrow(() => requireExpectedSource("a".repeat(40)));
  assert.doesNotThrow(() => requireExpectedSource("a".repeat(40), "a".repeat(40)));
  assert.throws(() => requireExpectedSource("a".repeat(40), "b".repeat(40)), /approved release/);
});
