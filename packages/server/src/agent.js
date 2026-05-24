// Spawns claude-code as a subprocess, parses its stream-json output,
// translates to our SSE event contract. Mirrors LarksorTC/bridge.py logic.

import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { config, logger } from "./config.js";
import { workspaceDir, claudeConfigDir, logUsage, appendTurn } from "./store.js";
import { wrapBuddyPrompt, postProcess } from "./buddy.js";

const log = logger("info");
const dbg = logger("debug");

// Map our "model" alias to the underlying claude-code model string. The
// claude-code runtime then uses ANTHROPIC_DEFAULT_*_MODEL to map shapes to
// DeepSeek model IDs.
function resolveModel(alias) {
  switch ((alias || "auto").toLowerCase()) {
    case "auto":
    case "sonnet":   return undefined;                 // let claude default
    case "flash":
    case "haiku":    return config.haikuModel;
    case "pro":      return "deepseek-v4-pro";
    case "pro-1m":
    case "pro[1m]":
    case "opus":     return config.opusModel;
    default:         return alias;                     // explicit deepseek-* id
  }
}

function envForChild(uid) {
  return {
    ...process.env,
    HOME: workspaceDir(uid, ".home"),                  // sandbox claude-code's $HOME
    CLAUDE_CONFIG_DIR: claudeConfigDir(uid),
    ANTHROPIC_BASE_URL: config.anthropicBaseUrl,
    ANTHROPIC_AUTH_TOKEN: config.anthropicAuthToken,
    ANTHROPIC_MODEL: config.anthropicModel,
    ANTHROPIC_DEFAULT_HAIKU_MODEL: config.haikuModel,
    ANTHROPIC_DEFAULT_SONNET_MODEL: config.sonnetModel,
    ANTHROPIC_DEFAULT_OPUS_MODEL: config.opusModel,
    CLAUDE_CODE_SUBAGENT_MODEL: config.subagentModel,
    DISABLE_TELEMETRY: "1",
  };
}

// Tracks running children so /v1/cancel/<sid> can SIGINT them.
const running = new Map();    // session_id → child process

export function cancel(sessionId) {
  const p = running.get(sessionId);
  if (!p) return false;
  try { p.kill("SIGINT"); return true; } catch { return false; }
}

/**
 * Run one turn. Yields SSE-shaped events:
 *   { event: "session"|"thinking"|"tool_call"|"tool_result"|"delta"|"usage"|"done"|"error",
 *     data: <object> }
 */
export async function* runAgent(uid, { prompt, model, sessionId, claudeSessionId, workspace, permissionMode, mode, context }) {
  const sid = sessionId || randomUUID();
  const ws = workspaceDir(uid, workspace);
  const resolvedModel = resolveModel(model);
  const effectivePrompt = mode === "buddy" ? wrapBuddyPrompt(prompt, context) : prompt;
  const args = [
    "--print", "--output-format", "stream-json", "--verbose",
    "--permission-mode", permissionMode || config.defaultPermissionMode,
  ];
  if (resolvedModel) args.push("--model", resolvedModel);
  // Only --resume when we have a real claude-managed session id (not our own
  // UUID). Passing an unknown UUID to --resume makes claude exit silently.
  if (claudeSessionId) args.push("--resume", claudeSessionId);
  args.push(effectivePrompt);

  yield { event: "session", data: { session_id: sid, created: Date.now() } };

  let child;
  try {
    child = spawn(config.claudeBin, args, {
      cwd: ws,
      env: envForChild(uid),
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (e) {
    yield { event: "error", data: { code: "agent_crash", message: `failed to spawn: ${e.message}`, hint: "Ensure claude-code is installed: npm i -g @anthropic-ai/claude-code" } };
    return;
  }
  running.set(sid, child);

  const timeoutHandle = setTimeout(() => {
    log(`agent timeout (${config.agentTimeoutMs}ms), SIGKILL`);
    try { child.kill("SIGKILL"); } catch {}
  }, config.agentTimeoutMs);

  let stderrBuf = "";
  child.stderr.on("data", chunk => { stderrBuf += chunk.toString("utf-8"); });

  let usageTotal = { input_tokens: 0, output_tokens: 0, cached_tokens: 0, cost_usd: 0 };
  let answerBuf = [];
  let finalText = "";
  let lineBuf = "";
  const toolIndex = new Map();

  try {
    for await (const chunk of child.stdout) {
      lineBuf += chunk.toString("utf-8");
      let nl;
      while ((nl = lineBuf.indexOf("\n")) !== -1) {
        const line = lineBuf.slice(0, nl).trim();
        lineBuf = lineBuf.slice(nl + 1);
        if (!line) continue;
        if (!line.startsWith("{")) {
          dbg("non-json line:", line.slice(0, 200));
          continue;
        }
        let evt;
        try { evt = JSON.parse(line); } catch { continue; }
        for (const out of translateEvent(evt, { answerBuf, toolIndex, usageTotal })) {
          yield out;
        }
        if (evt.type === "result") {
          let raw = (evt.result || "").trim() || answerBuf.join("").trim() || "(empty)";
          finalText = mode === "buddy" ? postProcess(raw) : raw;
          if (evt.session_id && evt.session_id !== sid) {
            // claude-code may rename the session id on resume; tell client
            yield { event: "session", data: { session_id: evt.session_id, created: Date.now() } };
          }
          const u = evt.usage || {};
          usageTotal = {
            input_tokens: u.input_tokens || 0,
            output_tokens: u.output_tokens || 0,
            cached_tokens: (u.cache_read_input_tokens || 0) + (u.cache_creation_input_tokens || 0),
            cost_usd: +evt.total_cost_usd || 0,
          };
        }
      }
    }

    const code = await new Promise(r => child.on("close", c => r(c)));
    clearTimeout(timeoutHandle);
    running.delete(sid);

    if (!finalText && code !== 0) {
      const hint = pickHint(stderrBuf);
      yield { event: "error", data: { code: "agent_crash", message: `agent exited rc=${code}`, hint, stderr: stderrBuf.slice(-600) } };
      return;
    }

    // persist turn
    try {
      await appendTurn(uid, sid, {
        ts: Date.now(),
        prompt, model: resolvedModel || "auto",
        result: finalText.slice(0, 8000),
        usage: usageTotal,
        cost_usd: usageTotal.cost_usd,
      });
      logUsage(uid, { session_id: sid, model: resolvedModel || "auto", ...usageTotal });
    } catch (e) {
      log("persist turn fail:", e.message);
    }

    yield { event: "done", data: { result: finalText, usage_total: usageTotal, cost_usd_total: usageTotal.cost_usd, num_turns: 1 } };
  } catch (e) {
    clearTimeout(timeoutHandle);
    running.delete(sid);
    yield { event: "error", data: { code: "agent_crash", message: e.message, hint: "Internal exception parsing agent stream" } };
  }
}

function pickHint(stderr) {
  const s = (stderr || "").toLowerCase();
  if (s.includes("resource_exhausted")) return "DeepSeek returned resource_exhausted. Try starting a new session.";
  if (s.includes("max mode required"))  return "This model needs Max Mode enabled in cli-config.";
  if (s.includes("rate limit") || s.includes("429")) return "Rate-limited by DeepSeek. Wait a minute and retry.";
  if (s.includes("invalid api key") || s.includes("401")) return "DeepSeek API key invalid. Check env.sh.";
  return "Check server logs for the full stderr.";
}

function* translateEvent(evt, { answerBuf, toolIndex, usageTotal }) {
  const t = evt.type;
  const sub = evt.subtype;
  if (t === "tool_call") {
    if (sub === "started") {
      toolIndex.set(evt.id, evt);
      yield { event: "tool_call", data: {
        id: evt.id, name: evt.name || evt.tool_name || "(tool)",
        args_preview: shortPreview(evt.input || evt.args), status: "started",
      } };
    } else if (sub === "completed") {
      const rc = evt.rc ?? evt.return_code ?? null;
      yield { event: "tool_result", data: {
        id: evt.id, ok: !evt.error && !(rc !== null && rc >= 2),
        rc, elapsed_ms: evt.elapsed_ms,
      } };
    }
  } else if (t === "thinking" && sub === "delta") {
    const text = evt.text || "";
    if (text) yield { event: "thinking", data: { delta: text } };
  } else if (t === "assistant") {
    const msg = evt.message || {};
    for (const c of (msg.content || [])) {
      if (c.type === "text" && c.text) {
        answerBuf.push(c.text);
        yield { event: "delta", data: { text: c.text } };
      }
      // NOTE: postProcess() runs on the final aggregated text in the
      // result block; we deliberately do NOT rewrite per-chunk because
      // a path like /Users/x might be split across deltas. The mobile
      // PWA and SwiftUI desktop already show the streamed text raw —
      // they'll see the post-processed version on the `done` frame.
    }
  } else if (t === "system" && evt.usage) {
    yield { event: "usage", data: {
      input_tokens: evt.usage.input_tokens || 0,
      output_tokens: evt.usage.output_tokens || 0,
      cached_tokens: evt.usage.cache_read_input_tokens || 0,
      cost_usd: +evt.cost_usd || 0,
    } };
  }
}

function shortPreview(obj, n = 80) {
  if (obj == null) return "";
  let s; try { s = typeof obj === "string" ? obj : JSON.stringify(obj); } catch { s = String(obj); }
  if (s.length > n) s = s.slice(0, n) + "…";
  return s;
}
