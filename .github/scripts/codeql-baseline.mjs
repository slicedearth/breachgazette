import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { REPOSITORY } from "./publication-policy.mjs";

export const CONFIGURATIONS = ["ci", "codeql"].flatMap((workflow) =>
  ["python", "javascript-typescript"].map((language) => ({
    analysis_key: `.github/workflows/${workflow}.yml:analyze`,
    category: `.github/workflows/${workflow}.yml:analyze/language:${language}`,
  })),
);

export function reconcile(analyses, ref, revision) {
  if (!Array.isArray(analyses) || !/^[0-9a-f]{40}$/.test(revision)) {
    throw new Error("Invalid CodeQL analysis evidence.");
  }
  return CONFIGURATIONS.map((configuration) => {
    const latest = analyses.filter((analysis) =>
      analysis.ref === ref && analysis.analysis_key === configuration.analysis_key &&
      analysis.category === configuration.category && analysis.tool?.name === "CodeQL"
    ).sort((left, right) => right.id - left.id)[0];
    const status = !latest ? "missing" : latest.commit_sha !== revision ? "stale" :
      latest.error !== "" ? "failed" : "current";
    return { ...configuration, status, analysis_id: latest?.id ?? null };
  });
}

function main() {
  const pull = process.argv[2];
  if (!/^[1-9][0-9]*$/.test(pull ?? "")) throw new Error("Provide a pull request number.");
  const api = (path, paginate = false) => JSON.parse(execFileSync("gh",
    ["api", path, ...(paginate ? ["--paginate", "--slurp"] : [])],
    { encoding: "utf8", timeout: 60_000, maxBuffer: 20_000_000 },
  ));
  const prefix = `repos/${REPOSITORY}`;
  const pr = api(`${prefix}/pulls/${pull}`);
  if (pr.state !== "open" || pr.base?.ref !== "main" || !pr.merge_commit_sha) {
    throw new Error("Baseline review requires an open main-targeted PR with a merge revision.");
  }
  const base = api(`${prefix}/branches/main`).commit.sha;
  let passed = true;
  for (const [ref, revision] of [["refs/heads/main", base], [`refs/pull/${pull}/merge`, pr.merge_commit_sha]]) {
    const analyses = api(`${prefix}/code-scanning/analyses?ref=${encodeURIComponent(ref)}&tool_name=CodeQL&per_page=100`, true).flat();
    const configurations = reconcile(analyses, ref, revision);
    passed &&= configurations.every((item) => item.status === "current");
    console.log(JSON.stringify({ ref, revision, configurations }));
  }
  // Ref movement invalidates the comparison, even if the previous snapshots agreed.
  const finalPR = api(`${prefix}/pulls/${pull}`);
  if (api(`${prefix}/branches/main`).commit.sha !== base ||
      finalPR.merge_commit_sha !== pr.merge_commit_sha || finalPR.state !== "open") {
    throw new Error("References changed during baseline review; repeat the read-only check.");
  }
  if (!passed) process.exitCode = 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try { main(); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
