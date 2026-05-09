#!/usr/bin/env node
/**
 * deepseek-harness-mcp · MCP server.
 *
 * Run via:
 *   npx -y @deepseek-harness/mcp
 *
 * Wire it into Claude Desktop / Cursor / Cline / ChatWise / Cherry Studio
 * by adding to your MCP config:
 *
 *   {
 *     "mcpServers": {
 *       "deepseek-harness": {
 *         "command": "npx",
 *         "args": ["-y", "@deepseek-harness/mcp"],
 *         "env": { "DEEPSEEK_API_KEY": "sk-..." }
 *       }
 *     }
 *   }
 *
 * Exposes 4 tools whose names are stable across versions (semver-major bumps if changed):
 *   - deepseek_chat              (non-streaming completion w/ all guards)
 *   - deepseek_chat_stream       (streaming, same guards; emits one final aggregated message)
 *   - validate_message_history   (pre-flight contract audit; no API call)
 *   - estimate_cache_hit         (pre-flight cache estimate; no API call)
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

import {
  safeDeepSeekCall,
  safeDeepSeekStream,
  validateHistory,
  prepareForNewUserTurn,
} from "./safe_call.js";

const SERVER_NAME = "deepseek-harness";
const SERVER_VERSION = "0.2.0";

const TOOLS = [
  {
    name: "deepseek_chat",
    description:
      "Call DeepSeek V4-Pro / V4-Flash with all 10 protocol contract rules enforced. " +
      "Use this instead of raw OpenAI client to avoid the 16 documented quirks " +
      "(reasoning_content lifecycle, tool-call leakage, max_tokens runaway, etc.). " +
      "Returns the assistant message PLUS reasoning_content (if thinking was on) so the " +
      "caller can re-send it in a multi-turn loop without 400.",
    inputSchema: {
      type: "object",
      properties: {
        messages: { type: "array", description: "OpenAI-shape messages list." },
        model: { type: "string", default: "deepseek-v4-pro", description: "deepseek-v4-pro or deepseek-v4-flash" },
        enable_thinking: { type: "boolean", default: false, description: "Enable thinking mode (off by default to save reasoning tokens)." },
        max_tokens: { type: "integer", default: 4096, description: "Output cap (must be set; default 4096)." },
        temperature: { type: "number", description: "Sampling temperature." },
        tools: { type: "array", description: "OpenAI-shape function tool defs." },
        tool_choice: { description: "auto | none | {type:function,function:{name:'X'}}" },
      },
      required: ["messages"],
    },
  },
  {
    name: "deepseek_chat_stream",
    description:
      "Streaming variant of deepseek_chat. Aggregates stream events server-side and returns ONE " +
      "final assistant message + final usage block. Recommended for long-output scenarios where " +
      "the calling agent does not want to handle SSE chunking.",
    inputSchema: {
      type: "object",
      properties: {
        messages: { type: "array" },
        model: { type: "string", default: "deepseek-v4-pro" },
        enable_thinking: { type: "boolean", default: false },
        max_tokens: { type: "integer", default: 4096 },
        temperature: { type: "number" },
        tools: { type: "array" },
        tool_choice: {},
      },
      required: ["messages"],
    },
  },
  {
    name: "validate_message_history",
    description:
      "Pre-flight audit. Checks a messages.json against the 5 most common contract violations. " +
      "Returns {ok, violations[]} without calling the API. Useful when an agent constructs a " +
      "history manually and wants to know if DeepSeek will 400 before paying for a request.",
    inputSchema: {
      type: "object",
      properties: { messages: { type: "array" } },
      required: ["messages"],
    },
  },
  {
    name: "estimate_cache_hit",
    description:
      "Approximate how many tokens of `messages` will hit DeepSeek's prefix cache compared to " +
      "`previous_prefix`. No API call, uses a local tokenizer approximation. Returns " +
      "{common_prefix_tokens, eligible_cached_tokens, estimated_hit_rate, explanation}. Granularity " +
      "is rounded to 256-token blocks per spec §4.",
    inputSchema: {
      type: "object",
      properties: {
        messages: { type: "array" },
        previous_prefix: { type: "array", description: "Optional; prior request body for diff." },
      },
      required: ["messages"],
    },
  },
] as const;

async function main() {
  const server = new Server(
    { name: SERVER_NAME, version: SERVER_VERSION },
    { capabilities: { tools: {} } },
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: TOOLS.map((t) => ({ ...t })),
  }));

  server.setRequestHandler(CallToolRequestSchema, async (req) => {
    const { name, arguments: args } = req.params;
    try {
      switch (name) {
        case "deepseek_chat": {
          const out = await safeDeepSeekCall(adaptArgs(args));
          return jsonResult(out);
        }
        case "deepseek_chat_stream": {
          // Aggregate streaming events into a single final response.
          const events = [];
          let finalEvent: any = null;
          for await (const evt of safeDeepSeekStream(adaptArgs(args))) {
            events.push(evt);
            if ((evt as any).type === "done") finalEvent = evt;
          }
          return jsonResult({
            ...(finalEvent ?? {}),
            n_stream_events: events.length,
          });
        }
        case "validate_message_history": {
          const result = validateHistory((args as any).messages);
          return jsonResult(result);
        }
        case "estimate_cache_hit": {
          const out = estimateCacheHitLocal(
            (args as any).messages,
            (args as any).previous_prefix,
          );
          return jsonResult(out);
        }
        default:
          return errorResult(`unknown tool: ${name}`);
      }
    } catch (e: any) {
      return errorResult(`${e?.constructor?.name ?? "Error"}: ${e?.message ?? String(e)}`);
    }
  });

  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error(`[deepseek-harness-mcp] ready · ${TOOLS.length} tools · v${SERVER_VERSION}`);
}

function jsonResult(obj: any) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(obj, null, 2) }],
  };
}

/** MCP arg names are snake_case per JSON-Schema; safe_call.ts reads camelCase. Bridge them here. */
function adaptArgs(args: any): any {
  const a = args ?? {};
  return {
    messages: a.messages,
    model: a.model,
    tools: a.tools,
    toolChoice: a.tool_choice ?? a.toolChoice,
    enableThinking: a.enable_thinking ?? a.enableThinking,
    maxTokens: a.max_tokens ?? a.maxTokens,
    temperature: a.temperature,
    extraBody: a.extra_body ?? a.extraBody,
  };
}

function errorResult(msg: string) {
  return { content: [{ type: "text" as const, text: msg }], isError: true };
}

/** Local cache-hit estimator. Rough, no tokenizer dep — counts UTF-8 bytes / 3.6 as token approximation. */
function estimateCacheHitLocal(newMessages: any[], previousMessages?: any[]) {
  const CACHE_BLOCK = 256;
  const MIN_PREFIX = 1024;
  const newText = serializeMessages(newMessages);
  const prevText = serializeMessages(previousMessages ?? []);
  const commonChars = longestCommonPrefix(newText, prevText);
  const newApproxTokens = Math.ceil(newText.length / 3.6);
  const commonApproxTokens = Math.ceil(commonChars / 3.6);
  const eligible =
    commonApproxTokens >= MIN_PREFIX
      ? Math.floor(commonApproxTokens / CACHE_BLOCK) * CACHE_BLOCK
      : 0;
  return {
    common_prefix_tokens_approx: commonApproxTokens,
    eligible_cached_tokens: eligible,
    new_total_tokens_approx: newApproxTokens,
    estimated_hit_rate: newApproxTokens ? Math.round((eligible / newApproxTokens) * 10000) / 10000 : 0,
    minimum_prefix_threshold: MIN_PREFIX,
    cache_block_size: CACHE_BLOCK,
    explanation:
      commonApproxTokens < MIN_PREFIX
        ? `common prefix < ${MIN_PREFIX} tokens — server will not cache this request`
        : `${eligible} tokens (rounded to ${CACHE_BLOCK}-block) will be discounted at $0.0028/M`,
  };
}

function serializeMessages(messages: any[]): string {
  const parts: string[] = [];
  for (const m of messages) {
    parts.push(`<role>${m.role ?? ""}</role>`);
    if (typeof m.content === "string") parts.push(`<content>${m.content}</content>`);
    for (const tc of m.tool_calls ?? []) {
      parts.push(`<tc>${tc.id ?? ""}|${tc.function?.name ?? ""}|${tc.function?.arguments ?? ""}</tc>`);
    }
    if (m.tool_call_id) parts.push(`<tcid>${m.tool_call_id}</tcid>`);
    if (m.reasoning_content) parts.push(`<rc>${m.reasoning_content}</rc>`);
  }
  return parts.join("\n");
}

function longestCommonPrefix(a: string, b: string): number {
  const n = Math.min(a.length, b.length);
  let i = 0;
  while (i < n && a.charCodeAt(i) === b.charCodeAt(i)) i++;
  return i;
}

main().catch((e) => {
  console.error("[deepseek-harness-mcp] fatal:", e);
  process.exit(1);
});
