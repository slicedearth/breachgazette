import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { spawn } from "node:child_process";

const source = readFileSync(new URL("../build-with-budget.mjs", import.meta.url), "utf8")
  .replace(/^import .+;\s*$/gm, "");

function harness() {
  const child = new EventEmitter();
  child.pid = 1234;
  const signals = [];
  child.kill = (signal) => { signals.push(signal); return true; };
  const output = [];
  const errors = [];
  const cleared = [];
  const timers = [];
  let now = 0;
  const runtimeProcess = { platform: "linux", env: { SYNTHETIC_TEST: "1" },
    kill(pid, signal) { assert.equal(pid, -child.pid); signals.push(signal); } };
  const scope = {
    spawn(command, args, options) {
      assert.equal(command, "npm");
      assert.deepEqual(Array.from(args), ["run", "build"]);
      assert.equal(options.env, runtimeProcess.env);
      assert.equal(options.stdio, "inherit");
      assert.equal(options.detached, true);
      return child;
    },
    performance: { now: () => now },
    setTimeout(callback, milliseconds) { timers.push({ callback, milliseconds }); return timers.length; },
    clearTimeout(id) { cleared.push(id); },
    console: { log: (value) => output.push(value), error: (value) => errors.push(value) },
    process: runtimeProcess,
  };
  new vm.Script(source, { filename: "build-with-budget.mjs" }).runInNewContext(scope);
  return {
    child, signals, output, errors, cleared, timer: timers[0], timers, runtimeProcess,
    advance(milliseconds) { now += milliseconds; },
  };
}

test("successful builds report elapsed time and clear the fixed timer", () => {
  const run = harness();
  assert.equal(run.timer.milliseconds, 120_000);
  run.advance(750);
  run.child.emit("close", 0, null);
  assert.deepEqual(run.cleared, [1]);
  assert.deepEqual(run.signals, []);
  assert.equal(run.runtimeProcess.exitCode, undefined);
  assert.match(run.output[0], /0\.75 seconds/);
  assert.deepEqual(run.errors, []);
});

test("failed builds retain their exit status without reporting success", () => {
  const run = harness();
  run.child.emit("close", 2, null);
  assert.equal(run.runtimeProcess.exitCode, 2);
  assert.match(run.errors[0], /exit code 2/);
  assert.deepEqual(run.output, []);
});

test("expired budgets request termination and report failure on subprocess close", () => {
  const run = harness();
  run.advance(120_000);
  run.timer.callback();
  assert.deepEqual(run.signals, ["SIGTERM"]);
  assert.equal(run.timers[1].milliseconds, 5_000);
  run.child.emit("close", null, "SIGTERM");
  assert.equal(run.runtimeProcess.exitCode, 1);
  assert.match(run.errors[0], /exceeded the 120-second budget/);
  assert.deepEqual(run.output, []);
  run.timers[1].callback();
  assert.deepEqual(run.signals, ["SIGTERM", "SIGKILL"]);
});

test("spawn errors clear the timer and return a failure status", () => {
  const run = harness();
  run.child.emit("error", new Error("synthetic spawn failure"));
  assert.deepEqual(run.cleared, [1, undefined]);
  assert.equal(run.runtimeProcess.exitCode, 1);
  assert.match(run.errors[0], /Unable to start the production build/);
});

test("the bounded wrapper kills a real uncooperative POSIX process tree", { skip: process.platform === "win32", timeout: 10_000 }, async () => {
  const descendant = `process.on('SIGTERM', () => {}); console.log('fixture-pid:' + process.pid); setInterval(() => {}, 1000);`;
  const childCode = `const {spawn}=require('node:child_process'); ${descendant}
    spawn(process.execPath, ['-e', ${JSON.stringify(descendant)}], {stdio:'inherit'});`;
  const actual = readFileSync(new URL("../build-with-budget.mjs", import.meta.url), "utf8")
    .replace("120_000", "1_000").replace("5_000", "200")
    .replace('spawn(npm, ["run", "build"]', `spawn(process.execPath, ['-e', ${JSON.stringify(childCode)}]`);
  const wrapper = spawn(process.execPath, ["--input-type=module", "--eval", actual], { stdio: ["ignore", "pipe", "pipe"] });
  let output = "";
  let errors = "";
  wrapper.stdout.on("data", (chunk) => { output += chunk; });
  wrapper.stderr.on("data", (chunk) => { errors += chunk; });
  const emergency = setTimeout(() => {
    wrapper.kill("SIGKILL");
    for (const match of output.matchAll(/fixture-pid:(\d+)/g)) {
      try { process.kill(Number(match[1]), "SIGKILL"); } catch { /* already exited */ }
    }
  }, 8_000);
  try {
    const code = await new Promise((resolve, reject) => {
      wrapper.on("error", reject);
      wrapper.on("close", resolve);
    });
    assert.equal(code, 1);
    assert.equal([...output.matchAll(/fixture-pid:(\d+)/g)].length, 2);
    assert.match(errors, /exceeded the 1-second budget/);
    // Both processes inherited the output pipes. Close is emitted only after
    // every writer is terminated; SIGTERM handlers deliberately did nothing.
  } finally { clearTimeout(emergency); }
});
