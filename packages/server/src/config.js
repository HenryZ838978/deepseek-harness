// Central config + env loading. No deps.
//
// Resolution order for each setting:
//   1. process.env (highest)
//   2. /data/<uid>/env.json (per-user, multi-tenant cloud)
//   3. ~/Library/Application Support/DeepSeekHarness/env.sh (macOS desktop)
//   4. ~/.whalecode/env.sh (legacy desktop, back-compat)
//   5. ~/.config/dsh/env.sh (Linux)
//   6. baked-in defaults

import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const HOME = homedir();

const ENV_FILE_CANDIDATES = [
  process.env.DSH_ENV_FILE,
  join(HOME, "Library/Application Support/DeepSeekHarness/env.sh"),
  join(HOME, ".whalecode/env.sh"),
  join(HOME, ".config/dsh/env.sh"),
].filter(Boolean);

function parseShellEnv(text) {
  const out = {};
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const m = line.match(/^(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$/);
    if (!m) continue;
    let val = m[2].trim();
    if ((val.startsWith('"') && val.endsWith('"')) ||
        (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    }
    // strip inline shell var fallbacks: "${X:-default}" → "default" if X unset
    val = val.replace(/\$\{([A-Z_][A-Z0-9_]*):-([^}]*)\}/g, (_, k, def) =>
      out[k] ?? process.env[k] ?? def);
    val = val.replace(/\$([A-Z_][A-Z0-9_]*)/g, (_, k) =>
      out[k] ?? process.env[k] ?? "");
    out[m[1]] = val;
  }
  return out;
}

function loadEnvFiles() {
  const merged = {};
  for (const path of ENV_FILE_CANDIDATES) {
    if (existsSync(path)) {
      try {
        const parsed = parseShellEnv(readFileSync(path, "utf-8"));
        for (const [k, v] of Object.entries(parsed)) {
          if (merged[k] === undefined) merged[k] = v;
        }
      } catch (e) {
        console.warn(`[config] failed to read ${path}: ${e.message}`);
      }
    }
  }
  return merged;
}

const fileEnv = loadEnvFiles();
const env = (key, fallback) => process.env[key] ?? fileEnv[key] ?? fallback;

export const config = {
  // server
  host: env("DSH_HOST", "127.0.0.1"),
  port: parseInt(env("DSH_PORT", "7777"), 10),
  authMode: env("DSH_AUTH_MODE", "none"),                  // "none" | "bearer"
  jwtSecret: env("DSH_JWT_SECRET", "dev-secret-rotate-me"),
  allowedOrigins: env("DSH_ALLOWED_ORIGINS", "*").split(",").map(s => s.trim()),
  dataDir: env("DSH_DATA_DIR", join(HOME, ".local/share/deepseek-harness/data")),
  logLevel: env("DSH_LOG_LEVEL", "info"),
  agentTimeoutMs: parseInt(env("DSH_AGENT_TIMEOUT_MS", "900000"), 10),  // 15 min
  rateLimitPerMin: parseInt(env("DSH_RATE_LIMIT_PER_MIN", "30"), 10),

  // claude-code / anthropic-shape backend
  anthropicBaseUrl: env("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic"),
  anthropicAuthToken: env("ANTHROPIC_AUTH_TOKEN", env("DEEPSEEK_API_KEY", "")),
  anthropicModel: env("ANTHROPIC_MODEL", "deepseek-v4-pro[1m]"),
  haikuModel: env("ANTHROPIC_DEFAULT_HAIKU_MODEL", "deepseek-v4-flash"),
  sonnetModel: env("ANTHROPIC_DEFAULT_SONNET_MODEL", "deepseek-v4-pro[1m]"),
  opusModel: env("ANTHROPIC_DEFAULT_OPUS_MODEL", "deepseek-v4-pro[1m]"),
  subagentModel: env("CLAUDE_CODE_SUBAGENT_MODEL", "deepseek-v4-flash"),
  defaultPermissionMode: env("WC_DEFAULT_PERMISSION_MODE",
                             env("DSH_DEFAULT_PERMISSION_MODE", "bypassPermissions")),

  // claude-code binary location (auto-detected)
  claudeBin: env("DSH_CLAUDE_BIN", "claude"),

  // OTP / SMS (cloud only)
  otpProvider: env("DSH_OTP_PROVIDER", "mock"),            // "mock" | "aliyun"
  otpDevCode: env("DSH_OTP_DEV_CODE", "123456"),

  // version
  version: "0.1.0",
};

export function logger(level) {
  const order = { debug: 10, info: 20, warn: 30, error: 40 };
  const min = order[config.logLevel] ?? 20;
  return (...args) => {
    if (order[level] >= min) {
      const ts = new Date().toISOString();
      console.error(`[${ts}] ${level.toUpperCase().padEnd(5)}`, ...args);
    }
  };
}
