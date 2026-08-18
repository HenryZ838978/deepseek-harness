#!/usr/bin/env node
// dsh-doctor — meta-plugin shim. Delegates to the Python doctor.
//
// The official DeepSeek Harness Node runtime advertises "Everything is a
// Plugin". Fine. This plugin's job is to witness the runtime that hosts it.
// Actual probes live in the Python side (packages/cli/deepseek_harness_cli/
// doctor_node/), because that's where the harness's core witnesses already
// live and we don't want two places to maintain contracts.
//
// Usage (inside a dsh workspace or standalone):
//   dsh-doctor            # runs the full witness suite
//   dsh-doctor --json     # machine-readable
//   dsh-doctor --only P1-reasoner-skip,P2-bom
//
// Requires: `pip install deepseek-harness-cli` and DEEPSEEK_API_KEY in env
// for the live probes.

import { spawn } from "node:child_process"

const args = ["-m", "deepseek_harness_cli", "doctor", "--node", ...process.argv.slice(2)]

// Try `python3` then `python`.
const runners = ["python3", "python"]
let idx = 0

function tryNext() {
  if (idx >= runners.length) {
    console.error("dsh-doctor: no python interpreter found. Install python3 and `pip install deepseek-harness-cli`.")
    process.exit(127)
  }
  const bin = runners[idx++]
  const child = spawn(bin, args, { stdio: "inherit" })
  child.on("error", () => tryNext())
  child.on("exit", (code, signal) => {
    if (signal) process.kill(process.pid, signal)
    else process.exit(code ?? 0)
  })
}

tryNext()
