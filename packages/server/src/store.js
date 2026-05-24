// File-backed multi-tenant store. SQLite-free for v1 to avoid native deps in
// the container image. Layout under DSH_DATA_DIR:
//
//   <uid>/
//     env.json              user-scoped overrides (model, budget cap)
//     sessions/             one file per session
//       <session_id>.json   { id, title, model, created, last_active, turns: [...] }
//     usage.jsonl           append-only spend log
//     budget                daily cap (USD)
//
// Concurrency: each session file is read-modify-write under a per-session lock.

import { mkdirSync, existsSync, readFileSync, writeFileSync, readdirSync, appendFileSync, statSync, unlinkSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";
import { config, logger } from "./config.js";

const log = logger("debug");

const locks = new Map();              // session_id → Promise chain

function userDir(uid) {
  const dir = join(config.dataDir, uid);
  mkdirSync(join(dir, "sessions"), { recursive: true });
  return dir;
}

function readJSON(path, def) {
  if (!existsSync(path)) return def;
  try { return JSON.parse(readFileSync(path, "utf-8")); }
  catch (e) { log("readJSON fail", path, e.message); return def; }
}
function writeJSON(path, obj) {
  writeFileSync(path, JSON.stringify(obj, null, 2));
}

async function withLock(key, fn) {
  const prev = locks.get(key) ?? Promise.resolve();
  let release;
  const next = new Promise(r => { release = r; });
  locks.set(key, prev.then(() => next));
  await prev;
  try { return await fn(); }
  finally { release(); if (locks.get(key) === next) locks.delete(key); }
}

// ---- Sessions ----
export async function createSession(uid, { id, model, title }) {
  const dir = userDir(uid);
  const path = join(dir, "sessions", `${id}.json`);
  const session = {
    id, title: title || "(untitled)", model,
    created: Date.now(), last_active: Date.now(),
    turns: [], usage_total: 0, cost_usd_total: 0,
  };
  await withLock(id, () => writeJSON(path, session));
  return session;
}

export function getSession(uid, id) {
  const path = join(userDir(uid), "sessions", `${id}.json`);
  return readJSON(path, null);
}

export async function appendTurn(uid, id, turn) {
  const path = join(userDir(uid), "sessions", `${id}.json`);
  return withLock(id, () => {
    const s = readJSON(path, null);
    if (!s) return null;
    s.turns.push(turn);
    s.last_active = Date.now();
    s.cost_usd_total = (s.cost_usd_total || 0) + (turn.cost_usd || 0);
    if (!s.title || s.title === "(untitled)") {
      const firstPrompt = turn.prompt || "";
      s.title = firstPrompt.split("\n")[0].slice(0, 40) || "(untitled)";
    }
    writeJSON(path, s);
    return s;
  });
}

export function listSessions(uid) {
  const dir = join(userDir(uid), "sessions");
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter(f => f.endsWith(".json"))
    .map(f => {
      const s = readJSON(join(dir, f), null);
      if (!s) return null;
      return {
        id: s.id, title: s.title, model: s.model,
        last_active: s.last_active, cost_usd_total: s.cost_usd_total || 0,
        turn_count: (s.turns || []).length,
      };
    })
    .filter(Boolean)
    .sort((a, b) => b.last_active - a.last_active);
}

export function deleteSession(uid, id) {
  const path = join(userDir(uid), "sessions", `${id}.json`);
  if (existsSync(path)) unlinkSync(path);
  return true;
}

// ---- Budget / Usage ----
const DEFAULT_CAP = 5.00;

export function getBudget(uid) {
  const dir = userDir(uid);
  const capPath = join(dir, "budget");
  const cap = existsSync(capPath)
    ? parseFloat(readFileSync(capPath, "utf-8").trim()) || DEFAULT_CAP
    : DEFAULT_CAP;
  const usagePath = join(dir, "usage.jsonl");
  let today_usd = 0, month_usd = 0;
  if (existsSync(usagePath)) {
    const today = new Date().toISOString().slice(0, 10);
    const month = today.slice(0, 7);
    for (const ln of readFileSync(usagePath, "utf-8").split("\n")) {
      if (!ln) continue;
      try {
        const r = JSON.parse(ln);
        const ts = (r.ts || "").slice(0, 10);
        if (ts.startsWith(today)) today_usd += +r.cost_usd || 0;
        if (ts.startsWith(month)) month_usd += +r.cost_usd || 0;
      } catch {}
    }
  }
  return {
    today_usd: +today_usd.toFixed(4),
    cap_usd: cap,
    month_usd: +month_usd.toFixed(4),
    tier: "paid",
  };
}

export function setBudget(uid, capUsd) {
  const dir = userDir(uid);
  writeFileSync(join(dir, "budget"), String(capUsd));
  return getBudget(uid);
}

export function logUsage(uid, { session_id, model, cost_usd, input_tokens, output_tokens, cached_tokens }) {
  const dir = userDir(uid);
  const line = JSON.stringify({
    ts: new Date().toISOString(),
    session_id, model,
    cost_usd: +cost_usd || 0,
    input_tokens: +input_tokens || 0,
    output_tokens: +output_tokens || 0,
    cached_tokens: +cached_tokens || 0,
  });
  appendFileSync(join(dir, "usage.jsonl"), line + "\n");
}

export function isOverBudget(uid) {
  const b = getBudget(uid);
  return b.today_usd >= b.cap_usd;
}

// ---- Workspace dir resolution ----
//
// Buddy-mode design: non-technical users must never see the word "workspace".
// On the local desktop (uid === "local") we silently map the default workspace
// to ~/Documents/深求小助手/ — visible in Finder under the Chinese "文稿" folder,
// next to all the user's other documents. Multi-tenant cloud uids keep the
// hidden /data/<uid>/workspaces/<label>/ scheme.

const LOCAL_DEFAULT_WS = join(homedir(), "Documents", "深求小助手");

export function workspaceDir(uid, label) {
  if (uid === "local" && (!label || label === "default")) {
    mkdirSync(LOCAL_DEFAULT_WS, { recursive: true });
    return LOCAL_DEFAULT_WS;
  }
  if (uid === "local" && label && label !== "default") {
    // Named subfolder under the visible buddy folder
    const safe = label.replace(/[\\/]+/g, "_").slice(0, 64);
    const dir = join(LOCAL_DEFAULT_WS, safe);
    mkdirSync(dir, { recursive: true });
    return dir;
  }
  const safe = (label || "default").replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 32);
  const dir = join(userDir(uid), "workspaces", safe);
  mkdirSync(dir, { recursive: true });
  return dir;
}

export function claudeConfigDir(uid) {
  const dir = join(userDir(uid), ".claude");
  mkdirSync(dir, { recursive: true });
  return dir;
}
