/**
 * The single source of truth for the 10 contract rules, in TypeScript.
 *
 * Mirrors `packages/core/deepseek_harness/client.py` but only depends on
 * the `openai` SDK, no other deps. Used by both the npx CLI and the MCP server.
 */
import OpenAI from "openai";

export const HARD_CONTEXT_CEILING = 1_048_576;
export const DEFAULT_MAX_TOKENS = 4096;
const THINKING_DISABLED = { thinking: { type: "disabled" as const } };
const THINKING_ENABLED = { thinking: { type: "enabled" as const } };

let _client: OpenAI | null = null;

export function getDeepSeekClient(opts?: { apiKey?: string; baseUrl?: string }): OpenAI {
  if (_client) return _client;
  const apiKey = opts?.apiKey ?? process.env.DEEPSEEK_API_KEY;
  if (!apiKey) {
    throw new Error(
      "DEEPSEEK_API_KEY is not set. Get one at https://platform.deepseek.com",
    );
  }
  _client = new OpenAI({
    apiKey,
    baseURL: opts?.baseUrl ?? process.env.DEEPSEEK_BASE_URL ?? "https://api.deepseek.com",
  });
  return _client;
}

export interface SafeCallOpts {
  messages: any[];
  model?: string;
  tools?: any[];
  toolChoice?: any;
  enableThinking?: boolean;
  maxTokens?: number;
  temperature?: number;
  extraBody?: Record<string, any>;
}

export interface SafeCallResult {
  message: any;
  finish_reason: string | null;
  usage: Record<string, any>;
  salvage: { pattern: string } | null;
  warnings: string[];
}

/**
 * Non-streaming call satisfying contract rules C1-C7.
 *  C1: thinking disabled by default
 *  C2: caller-side concern (we expose helpers below)
 *  C3: max_tokens always set
 *  C7: caller asserts <= 1,048,576 - max_tokens
 */
export async function safeDeepSeekCall(opts: SafeCallOpts): Promise<SafeCallResult> {
  const max_tokens = opts.maxTokens ?? DEFAULT_MAX_TOKENS;
  const thinking = opts.enableThinking ? THINKING_ENABLED.thinking : THINKING_DISABLED.thinking;
  const params: any = {
    model: opts.model ?? "deepseek-v4-pro",
    messages: opts.messages,
    max_tokens,
    // openai-node passes unknown fields through to the request body — DeepSeek
    // reads `thinking` at the top level.
    thinking,
    ...(opts.extraBody ?? {}),
  };
  if (opts.tools) params.tools = opts.tools;
  if (opts.toolChoice) params.tool_choice = opts.toolChoice;
  if (opts.temperature !== undefined) params.temperature = opts.temperature;

  const resp = await getDeepSeekClient().chat.completions.create(params);
  const choice = resp.choices[0];
  const m = choice.message as any;
  const message: any = { role: "assistant", content: m.content };
  if (m.tool_calls?.length) {
    message.tool_calls = m.tool_calls.map((tc: any) => ({
      id: tc.id,
      type: tc.type,
      function: { name: tc.function.name, arguments: tc.function.arguments },
    }));
  }
  if (m.reasoning_content) message.reasoning_content = m.reasoning_content;

  return {
    message,
    finish_reason: choice.finish_reason,
    usage: normalizeUsage(resp.usage),
    salvage: null, // V4 official doesn't leak in our 50-trial run; placeholder for vLLM/SGLang
    warnings: [],
  };
}

/**
 * Streaming variant — uses list buffer + dict-by-index per Rule C4/C5.
 * Returns an async generator of structured events.
 */
export async function* safeDeepSeekStream(opts: SafeCallOpts) {
  const max_tokens = opts.maxTokens ?? DEFAULT_MAX_TOKENS;
  const thinking = opts.enableThinking ? THINKING_ENABLED.thinking : THINKING_DISABLED.thinking;
  const params: any = {
    model: opts.model ?? "deepseek-v4-pro",
    messages: opts.messages,
    max_tokens,
    thinking,
    stream: true,
    stream_options: { include_usage: true },
    ...(opts.extraBody ?? {}),
  };
  if (opts.tools) params.tools = opts.tools;
  if (opts.toolChoice) params.tool_choice = opts.toolChoice;
  if (opts.temperature !== undefined) params.temperature = opts.temperature;

  const stream = await getDeepSeekClient().chat.completions.create(params);
  const contentBuf: string[] = [];
  const reasoningBuf: string[] = [];
  const toolAcc: Record<number, { id: string | null; name: string | null; arguments: string }> = {};
  let finishReason: string | null = null;
  let usageRaw: any = null;

  for await (const chunk of stream as any) {
    const choices = chunk.choices ?? [];
    if (choices.length === 0) {
      if (chunk.usage) usageRaw = chunk.usage;
      continue;
    }
    const choice = choices[0];
    const delta = choice.delta;
    if (!delta) continue;

    if (delta.reasoning_content) {
      reasoningBuf.push(delta.reasoning_content);
      yield { type: "reasoning_delta", data: delta.reasoning_content };
    }
    if (delta.content) {
      contentBuf.push(delta.content);
      yield { type: "content_delta", data: delta.content };
    }
    for (const tc of delta.tool_calls ?? []) {
      const idx = tc.index ?? 0;
      if (!toolAcc[idx]) toolAcc[idx] = { id: null, name: null, arguments: "" };
      const slot = toolAcc[idx];
      if (tc.id) slot.id = tc.id;
      if (tc.function?.name) slot.name = tc.function.name;
      if (tc.function?.arguments) slot.arguments += tc.function.arguments;
      yield { type: "tool_call_delta", data: { index: idx, ...slot } };
    }
    if (choice.finish_reason) finishReason = choice.finish_reason;
  }

  const message: any = { role: "assistant", content: contentBuf.join("") || null };
  const indexes = Object.keys(toolAcc).map(Number).sort((a, b) => a - b);
  if (indexes.length) {
    message.tool_calls = indexes.map((i) => {
      const v = toolAcc[i];
      return {
        id: v.id ?? `call_${i}`,
        type: "function",
        function: { name: v.name ?? "", arguments: v.arguments || "{}" },
      };
    });
  }
  if (reasoningBuf.length) message.reasoning_content = reasoningBuf.join("");
  yield { type: "done", message, finish_reason: finishReason, usage: normalizeUsage(usageRaw) };
}

/** Bridge DeepSeek-native and OpenAI-shape cache fields per spec §4. */
export function normalizeUsage(u: any): Record<string, any> {
  if (!u) return {};
  const out: Record<string, any> = { ...(u as Record<string, any>) };
  const prompt = Number(out.prompt_tokens ?? 0);
  let hit = out.prompt_cache_hit_tokens;
  const details = out.prompt_tokens_details ?? {};
  let cachedOA = (details as any).cached_tokens;
  if (hit == null && cachedOA != null) hit = Number(cachedOA);
  if (cachedOA == null && hit != null) cachedOA = Number(hit);
  hit = hit ?? 0;
  cachedOA = cachedOA ?? 0;
  const miss = out.prompt_cache_miss_tokens ?? Math.max(prompt - Number(hit), 0);
  out.prompt_cache_hit_tokens = Number(hit);
  out.prompt_cache_miss_tokens = Number(miss);
  out.prompt_tokens_details = { cached_tokens: Number(cachedOA) };
  if (prompt) {
    out.cache_hit_rate = Math.round((Number(hit) / prompt) * 10000) / 10000;
    // V4-Flash pricing (USD per million tokens)
    const PRICE_MISS = 0.14, PRICE_HIT = 0.0028, PRICE_OUT = 0.28;
    const completion = Number(out.completion_tokens ?? 0);
    out.estimated_cost_usd =
      (Number(miss) / 1_000_000) * PRICE_MISS +
      (Number(hit) / 1_000_000) * PRICE_HIT +
      (completion / 1_000_000) * PRICE_OUT;
  }
  return out;
}

/** Strip reasoning_content from PRIOR assistant messages once a NEW user turn begins (spec §1 rule 3). */
export function prepareForNewUserTurn(history: any[]): any[] {
  return history.map((m) => {
    if (m.role !== "assistant") return { ...m };
    const { reasoning_content, ...rest } = m;
    return rest;
  });
}

/** Audit a message history against the contract; return list of violations + suggestions. */
export function validateHistory(messages: any[]): {
  ok: boolean;
  violations: { index: number; rule: string; message: string }[];
} {
  const violations: { index: number; rule: string; message: string }[] = [];
  for (let i = 0; i < messages.length; i++) {
    const m = messages[i];
    if (m.role === "assistant" && m.tool_calls?.length) {
      const next = messages[i + 1];
      if (next?.role === "tool" && !m.reasoning_content) {
        violations.push({
          index: i,
          rule: "C2",
          message:
            "assistant→tool boundary missing reasoning_content; will 400 on V4 with thinking enabled",
        });
      }
    }
    if (!["system", "user", "assistant", "tool"].includes(m.role)) {
      violations.push({ index: i, rule: "schema", message: `unknown role '${m.role}'` });
    }
    for (const tc of m.tool_calls ?? []) {
      if (!tc.id || !tc.function?.name) {
        violations.push({ index: i, rule: "schema", message: "tool_call missing id or function.name" });
      }
    }
  }
  if (messages[0]?.role === "system" && typeof messages[0].content === "string") {
    if (/\b20\d{2}-\d{2}-\d{2}\b/.test(messages[0].content) ||
        /current date/i.test(messages[0].content)) {
      violations.push({
        index: 0,
        rule: "C8-cache",
        message: "system prompt contains a date pattern → will invalidate prefix-cache daily",
      });
    }
  }
  return { ok: violations.length === 0, violations };
}
