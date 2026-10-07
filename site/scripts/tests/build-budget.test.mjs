import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../build-with-budget.mjs", import.meta.url), "utf8")
  .replace(/^import .+;\s*$/gm, "");

function harness() {
  const child = new EventEmitter();
  const signals = [];
  child.kill = (signal) => { signals.push(signal); return true; };
  const output = [];
  const errors = [];
  const cleared = [];
  let timer;
  let now = 0;
  const runtimeProcess = { platform: "linux", env: { SYNTHETIC_TEST: "1" } };
  const scope = {
    spawn(command, args, options) {
      assert.equal(command, "npm");
      assert.deepEqual(Array.from(args), ["run", "build"]);
      assert.equal(options.env, runtimeProcess.env);
      assert.equal(options.stdio, "inherit");
      return child;
    },
    performance: { now: () => now },
    setTimeout(callback, milliseconds) { timer = { callback, milliseconds }; return 1; },
    clearTimeout(id) { cleared.push(id); },
    console: { log: (value) => output.push(value), error: (value) => errors.push(value) },
    process: runtimeProcess,
  };
  new vm.Script(source, { filename: "build-with-budget.mjs" }).runInNewContext(scope);
  return {
    child, signals, output, errors, cleared, timer, runtimeProcess,
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
  run.child.emit("close", null, "SIGTERM");
  assert.equal(run.runtimeProcess.exitCode, 1);
  assert.match(run.errors[0], /exceeded the 120-second budget/);
  assert.deepEqual(run.output, []);
});

test("spawn errors clear the timer and return a failure status", () => {
  const run = harness();
  run.child.emit("error", new Error("synthetic spawn failure"));
  assert.deepEqual(run.cleared, [1]);
  assert.equal(run.runtimeProcess.exitCode, 1);
  assert.match(run.errors[0], /Unable to start the production build/);
});
