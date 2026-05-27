// Tiny JWT (HS256) + OTP gateway. No deps.
//
// JWT format: <base64url(header)>.<base64url(payload)>.<base64url(hmac)>
// We don't validate "alg" downgrade attacks because we only ever issue HS256.

import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { config, logger } from "./config.js";

const log = logger("info");

function b64url(buf) {
  return Buffer.from(buf).toString("base64")
    .replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
}
function b64urlDecode(str) {
  str = str.replace(/-/g, "+").replace(/_/g, "/");
  while (str.length % 4) str += "=";
  return Buffer.from(str, "base64");
}

export function signJWT(payload, ttlSeconds = 60 * 60 * 24 * 30) {
  const now = Math.floor(Date.now() / 1000);
  const full = { iat: now, exp: now + ttlSeconds, ...payload };
  const header = b64url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const body = b64url(JSON.stringify(full));
  const sig = b64url(createHmac("sha256", config.jwtSecret).update(`${header}.${body}`).digest());
  return `${header}.${body}.${sig}`;
}

export function verifyJWT(token) {
  if (!token || typeof token !== "string") return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [header, body, sig] = parts;
  const expected = createHmac("sha256", config.jwtSecret).update(`${header}.${body}`).digest();
  const provided = b64urlDecode(sig);
  if (expected.length !== provided.length) return null;
  if (!timingSafeEqual(expected, provided)) return null;
  let payload;
  try { payload = JSON.parse(b64urlDecode(body).toString("utf-8")); } catch { return null; }
  if (payload.exp && payload.exp < Math.floor(Date.now() / 1000)) return null;
  return payload;
}

// ---- OTP ----
// In-memory store, fine for v1 single-instance. Move to Redis for multi-replica.
const otpStore = new Map();   // phone → { code, expiresAt }

export function generateOTP(phone) {
  let code;
  if (config.otpProvider === "mock") {
    code = config.otpDevCode;
  } else {
    code = String(100000 + Math.floor(Math.random() * 900000));
  }
  otpStore.set(phone, { code, expiresAt: Date.now() + 5 * 60 * 1000 });
  log(`OTP for ${phone}: ${config.otpProvider === "mock" ? code : "(sent via SMS)"}`);
  // TODO: integrate Aliyun DYSMS when otpProvider === "aliyun"
  return { sent: true, devCode: config.otpProvider === "mock" ? code : undefined };
}

export function verifyOTP(phone, code) {
  const entry = otpStore.get(phone);
  if (!entry) return false;
  if (entry.expiresAt < Date.now()) { otpStore.delete(phone); return false; }
  if (entry.code !== code) return false;
  otpStore.delete(phone);
  return true;
}

// uid is deterministic from phone (so re-login yields same uid)
export function phoneToUid(phone) {
  const digest = createHmac("sha256", "uid-salt-v1").update(phone).digest("hex");
  return "u_" + digest.slice(0, 12);
}

// Express-style middleware. Returns uid for "none" mode (fixed "local"), or
// extracted uid from JWT in "bearer" mode. Returns null + writes 401 on failure.
export function requireAuth(req, res) {
  if (config.authMode === "none") return "local";
  const h = req.headers.authorization || "";
  const m = h.match(/^Bearer\s+(.+)$/i);
  if (!m) {
    res.writeHead(401, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: { code: "auth_required", message: "Bearer token required" } }));
    return null;
  }
  const payload = verifyJWT(m[1]);
  if (!payload) {
    res.writeHead(401, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: { code: "auth_expired", message: "Token invalid or expired" } }));
    return null;
  }
  return payload.sub;
}

export function randomNonce(bytes = 16) {
  return randomBytes(bytes).toString("hex");
}
