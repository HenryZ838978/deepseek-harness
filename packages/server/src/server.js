// HTTP + SSE server. Pure Node stdlib (http, url). No framework.

import { createServer } from "node:http";
import { randomUUID } from "node:crypto";
import { config, logger } from "./config.js";
import {
  requireAuth, signJWT, generateOTP, verifyOTP, phoneToUid,
} from "./auth.js";
import {
  createSession, getSession, listSessions, deleteSession,
  getBudget, setBudget, isOverBudget,
} from "./store.js";
import { runAgent, cancel } from "./agent.js";

const log = logger("info");

// ---- Rate limiting (sliding window per uid) ----
const hits = new Map();    // uid → [timestamp, ...]
function checkRate(uid) {
  const now = Date.now();
  const window = 60_000;
  const arr = (hits.get(uid) || []).filter(t => now - t < window);
  if (arr.length >= config.rateLimitPerMin) return false;
  arr.push(now);
  hits.set(uid, arr);
  return true;
}

// ---- helpers ----
function readBody(req, max = 16 * 1024 * 1024) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", c => {
      size += c.length;
      if (size > max) { reject(new Error("body too large")); req.destroy(); return; }
      chunks.push(c);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf-8")));
    req.on("error", reject);
  });
}

function json(res, status, obj) {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(obj));
}

function cors(req, res) {
  const origin = req.headers.origin;
  if (!origin) return;
  const allowed = config.allowedOrigins;
  if (allowed.includes("*") || allowed.includes(origin)) {
    res.setHeader("access-control-allow-origin", origin);
    res.setHeader("access-control-allow-credentials", "true");
    res.setHeader("access-control-allow-methods", "GET, POST, DELETE, OPTIONS");
    res.setHeader("access-control-allow-headers", "authorization, content-type");
    res.setHeader("vary", "origin");
  }
}

function sseInit(res) {
  res.writeHead(200, {
    "content-type": "text/event-stream; charset=utf-8",
    "cache-control": "no-cache, no-transform",
    "connection": "keep-alive",
    "x-accel-buffering": "no",                // disable nginx buffering
  });
  res.write(": connected\n\n");
}
function sseSend(res, event, data) {
  res.write(`event: ${event}\n`);
  res.write(`data: ${JSON.stringify(data)}\n\n`);
}

// ---- routes ----
async function route(req, res) {
  cors(req, res);
  if (req.method === "OPTIONS") { res.writeHead(204); res.end(); return; }

  const url = new URL(req.url, `http://${req.headers.host}`);
  const path = url.pathname;

  // health
  if (req.method === "GET" && path === "/health") {
    return json(res, 200, {
      ok: true, version: config.version, runtime: "claude-code",
      auth_mode: config.authMode,
      has_anthropic_key: !!config.anthropicAuthToken,
    });
  }

  // auth: send OTP
  if (req.method === "POST" && path === "/v1/auth/otp") {
    if (config.authMode === "none") return json(res, 404, { error: { code: "auth_disabled" } });
    const body = JSON.parse(await readBody(req) || "{}");
    if (!body.phone) return json(res, 400, { error: { code: "phone_required" } });
    const out = generateOTP(body.phone);
    return json(res, 200, out);
  }

  // auth: verify OTP + issue JWT
  if (req.method === "POST" && path === "/v1/auth/login") {
    if (config.authMode === "none") return json(res, 404, { error: { code: "auth_disabled" } });
    const body = JSON.parse(await readBody(req) || "{}");
    if (!body.phone || !body.otp) return json(res, 400, { error: { code: "phone_otp_required" } });
    if (!verifyOTP(body.phone, body.otp)) {
      return json(res, 401, { error: { code: "otp_invalid" } });
    }
    const uid = phoneToUid(body.phone);
    const token = signJWT({ sub: uid, tier: "paid" });
    return json(res, 200, { token, exp: Math.floor(Date.now()/1000) + 60*60*24*30, uid });
  }

  // everything below this needs auth
  const uid = requireAuth(req, res);
  if (!uid) return;

  if (req.method === "GET" && path === "/v1/sessions") {
    return json(res, 200, { sessions: listSessions(uid) });
  }

  let m;
  if (req.method === "GET" && (m = path.match(/^\/v1\/sessions\/([^/]+)$/))) {
    const s = getSession(uid, m[1]);
    if (!s) return json(res, 404, { error: { code: "session_not_found" } });
    return json(res, 200, s);
  }
  if (req.method === "DELETE" && (m = path.match(/^\/v1\/sessions\/([^/]+)$/))) {
    deleteSession(uid, m[1]);
    return json(res, 200, { ok: true });
  }

  if (req.method === "GET" && path === "/v1/budget") {
    return json(res, 200, getBudget(uid));
  }
  if (req.method === "POST" && path === "/v1/budget") {
    const body = JSON.parse(await readBody(req) || "{}");
    if (typeof body.cap_usd !== "number" || body.cap_usd < 0) {
      return json(res, 400, { error: { code: "cap_invalid" } });
    }
    return json(res, 200, setBudget(uid, body.cap_usd));
  }

  if (req.method === "POST" && (m = path.match(/^\/v1\/cancel\/([^/]+)$/))) {
    return json(res, 200, { ok: cancel(m[1]) });
  }

  if (req.method === "POST" && path === "/v1/run") {
    if (!checkRate(uid)) {
      res.setHeader("retry-after", "30");
      return json(res, 429, { error: { code: "rate_limited" } });
    }
    if (isOverBudget(uid)) {
      const b = getBudget(uid);
      return json(res, 402, { error: { code: "budget_exceeded", message: `today $${b.today_usd} >= cap $${b.cap_usd}`, hint: "raise via POST /v1/budget" } });
    }
    const body = JSON.parse(await readBody(req) || "{}");
    if (!body.prompt) return json(res, 400, { error: { code: "prompt_required" } });

    const sid = body.session_id || randomUUID();
    if (!body.session_id) {
      await createSession(uid, { id: sid, model: body.model || "auto", title: body.prompt.split("\n")[0].slice(0, 40) });
    }

    sseInit(res);
    // periodic keepalive to prevent intermediaries from closing idle stream
    const keepalive = setInterval(() => res.write(": ping\n\n"), 15000);
    req.on("close", () => { clearInterval(keepalive); cancel(sid); });
    try {
      for await (const evt of runAgent(uid, {
        prompt: body.prompt, model: body.model, sessionId: sid,
        workspace: body.workspace, permissionMode: body.permission_mode,
        mode: body.mode, context: body.context,
      })) {
        sseSend(res, evt.event, evt.data);
        if (evt.event === "done" || evt.event === "error") break;
      }
    } catch (e) {
      sseSend(res, "error", { code: "agent_crash", message: e.message });
    } finally {
      clearInterval(keepalive);
      res.end();
    }
    return;
  }

  return json(res, 404, { error: { code: "not_found", path } });
}

export function startServer() {
  const server = createServer(async (req, res) => {
    const started = Date.now();
    try {
      await route(req, res);
    } catch (e) {
      log("unhandled:", e);
      if (!res.headersSent) json(res, 500, { error: { code: "internal", message: e.message } });
    } finally {
      log(`${req.method} ${req.url} → ${res.statusCode || "?"} (${Date.now()-started}ms)`);
    }
  });

  server.listen(config.port, config.host, () => {
    log(`dsh server listening on http://${config.host}:${config.port}`);
    log(`  auth_mode = ${config.authMode}`);
    log(`  data_dir  = ${config.dataDir}`);
    log(`  anthropic = ${config.anthropicBaseUrl} (key: ${config.anthropicAuthToken ? "set" : "MISSING"})`);
    log(`  claude    = ${config.claudeBin}`);
  });

  for (const sig of ["SIGINT", "SIGTERM"]) {
    process.on(sig, () => { log(`${sig} received, shutting down`); server.close(() => process.exit(0)); });
  }

  return server;
}

if (import.meta.url === `file://${process.argv[1]}`) startServer();
