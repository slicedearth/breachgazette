import { spawn } from "node:child_process";
import { performance } from "node:perf_hooks";

const MAX_BUILD_MILLISECONDS = 120_000;
const TERMINATION_GRACE_MILLISECONDS = 5_000;
const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const started = performance.now();
let timedOut = false;
let forceTimer;
const processGroup = process.platform !== "win32";

const build = spawn(npm, ["run", "build"], {
  env: process.env,
  stdio: "inherit",
  detached: processGroup,
});

function terminate(signal) {
  try {
    if (processGroup && build.pid) process.kill(-build.pid, signal);
    else build.kill(signal);
  } catch (error) {
    if (error.code !== "ESRCH") {
      console.error(`Unable to terminate the production build: ${error.message}`);
      process.exitCode = 1;
    }
  }
}

const timer = setTimeout(() => {
  timedOut = true;
  process.exitCode = 1;
  terminate("SIGTERM");
  // Keep the grace timer even if npm exits while descendants retain the group.
  forceTimer = setTimeout(() => terminate("SIGKILL"), TERMINATION_GRACE_MILLISECONDS);
}, MAX_BUILD_MILLISECONDS);

build.on("error", (error) => {
  clearTimeout(timer);
  clearTimeout(forceTimer);
  console.error(`Unable to start the production build: ${error.message}`);
  process.exitCode = 1;
});

build.on("close", (code, signal) => {
  clearTimeout(timer);
  const elapsedSeconds = (performance.now() - started) / 1_000;
  if (timedOut) {
    console.error(
      `Production build exceeded the ${MAX_BUILD_MILLISECONDS / 1_000}-second budget.`,
    );
    process.exitCode = 1;
    return;
  }
  if (code !== 0) {
    console.error(`Production build failed with ${signal ?? `exit code ${code}`}.`);
    process.exitCode = code ?? 1;
    return;
  }
  console.log(`Production build completed in ${elapsedSeconds.toFixed(2)} seconds.`);
});
