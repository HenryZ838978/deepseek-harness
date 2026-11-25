"""Live sample: effort x tool-use latency and tool_choice x thinking contract.

Run on a host with network access to api.deepseek.com. Reads the API key from
stdin (one line) so it never lands in argv or a file on the remote host.
Writes one JSON object per request to the path in argv[1].

    python3 live_effort_tools.py out.jsonl [N] < keyfile

Two experiments, both against the Anthropic-Messages endpoint that the
official harness has used exclusively since 0.1.7 (`/anthropic/v1/messages`):

  A. effort matrix — model x effort(off/low/high/max) x prompt(tool-needed /
     tool-free) x N, streamed. Timings are wall-clock from request send:
     first byte, first thinking delta, first tool_use block, first text,
     end. This is what an agent loop's router turn costs per effort level.
  B. tool_choice contract — model x tool_choice(auto/any/tool) x thinking
     (enabled/disabled), non-streamed; on both endpoints (Messages + Chat).
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://api.deepseek.com"
KEY = sys.stdin.readline().strip()
OUT = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 4

TOOLS_A = [{
    "name": "get_weather", "description": "Get current weather for a city.",
    "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
}]
TOOLS_C = [{"type": "function", "function": {
    "name": "get_weather", "description": "Get current weather for a city.",
    "parameters": TOOLS_A[0]["input_schema"]}}]
PROMPTS = {
    "tool_needed": "北京现在天气怎么样？",
    "tool_free": "17 乘以 23 等于多少？只给数字。",
}


def _post(path: str, body: dict, headers: dict, stream: bool):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    return urllib.request.urlopen(req, timeout=300)


def messages_stream(model: str, effort: str, family: str, trial: int) -> dict:
    body = {"model": model, "max_tokens": 4096, "stream": True, "tools": TOOLS_A,
            "messages": [{"role": "user", "content": PROMPTS[family]}],
            "thinking": {"type": "disabled" if effort == "off" else "enabled"}}
    if effort != "off":
        body["output_config"] = {"effort": effort}
    rec = {"exp": "A", "model": model, "effort": effort, "family": family, "trial": trial}
    t0 = time.monotonic()
    marks: dict[str, float] = {}
    thinking_chars = 0
    blocks: list[str] = []
    try:
        with _post("/anthropic/v1/messages", body,
                   {"x-api-key": KEY, "anthropic-version": "2023-06-01"}, True) as r:
            for raw in r:
                now = time.monotonic() - t0
                marks.setdefault("first_byte", now)
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                ev = json.loads(line[5:])
                t = ev.get("type")
                if t == "message_start":
                    rec["resolved_model"] = ev["message"].get("model")
                    rec["usage_start"] = ev["message"].get("usage")
                elif t == "content_block_start":
                    bt = ev["content_block"]["type"]
                    blocks.append(bt)
                    marks.setdefault(f"first_{bt}", now)
                elif t == "content_block_delta":
                    d = ev["delta"]
                    if d.get("type") == "thinking_delta":
                        thinking_chars += len(d.get("thinking", ""))
                elif t == "message_delta":
                    rec["stop_reason"] = ev["delta"].get("stop_reason")
                    rec["usage_end"] = ev.get("usage")
        rec["ok"] = True
    except urllib.error.HTTPError as e:
        rec["ok"] = False
        rec["http"] = e.code
        rec["error"] = e.read().decode("utf-8", "replace")[:400]
    except Exception as e:  # network, timeout
        rec["ok"] = False
        rec["error"] = repr(e)[:400]
    rec["t_end"] = round(time.monotonic() - t0, 3)
    rec["marks"] = {k: round(v, 3) for k, v in marks.items()}
    rec["blocks"] = blocks
    rec["thinking_chars"] = thinking_chars
    return rec


def contract(endpoint: str, model: str, choice: str, thinking: str) -> dict:
    rec = {"exp": "B", "endpoint": endpoint, "model": model, "tool_choice": choice, "thinking": thinking}
    if endpoint == "messages":
        tc = {"auto": {"type": "auto"}, "any": {"type": "any"},
              "tool": {"type": "tool", "name": "get_weather"}}[choice]
        body = {"model": model, "max_tokens": 1024, "tools": TOOLS_A, "tool_choice": tc,
                "messages": [{"role": "user", "content": PROMPTS["tool_needed"]}],
                "thinking": {"type": thinking}}
        path, hdr = "/anthropic/v1/messages", {"x-api-key": KEY, "anthropic-version": "2023-06-01"}
    else:
        tc = {"auto": "auto", "any": "required",
              "tool": {"type": "function", "function": {"name": "get_weather"}}}[choice]
        body = {"model": model, "max_tokens": 1024, "tools": TOOLS_C, "tool_choice": tc,
                "messages": [{"role": "user", "content": PROMPTS["tool_needed"]}],
                "thinking": {"type": thinking}}
        path, hdr = "/chat/completions", {"Authorization": f"Bearer {KEY}"}
    t0 = time.monotonic()
    try:
        with _post(path, body, hdr, False) as r:
            d = json.load(r)
        rec["ok"] = True
        if endpoint == "messages":
            rec["resolved_model"] = d.get("model")
            rec["stop_reason"] = d.get("stop_reason")
            rec["blocks"] = [c["type"] for c in d.get("content", [])]
        else:
            c = d["choices"][0]
            rec["resolved_model"] = d.get("model")
            rec["stop_reason"] = c.get("finish_reason")
            rec["tool_calls"] = len(c["message"].get("tool_calls") or [])
            rec["reasoning"] = bool(c["message"].get("reasoning_content"))
        rec["usage"] = d.get("usage")
    except urllib.error.HTTPError as e:
        rec["ok"] = False
        rec["http"] = e.code
        rec["error"] = e.read().decode("utf-8", "replace")[:300]
    rec["t_end"] = round(time.monotonic() - t0, 3)
    return rec


def main() -> None:
    jobs = []
    for model in ("deepseek-flash", "deepseek-v4-pro"):
        for effort in ("off", "low", "high", "max"):
            for family in PROMPTS:
                for i in range(N):
                    jobs.append(lambda m=model, e=effort, f=family, i=i: messages_stream(m, e, f, i))
        for endpoint in ("messages", "chat"):
            for choice in ("auto", "any", "tool"):
                for thinking in ("enabled", "disabled"):
                    jobs.append(lambda ep=endpoint, m=model, c=choice, t=thinking: contract(ep, m, c, t))
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with ThreadPoolExecutor(max_workers=6) as pool, open(OUT, "w") as fh:
        for rec in pool.map(lambda j: j(), jobs):
            rec["sampled_at"] = stamp
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
    print(f"wrote {len(jobs)} records to {OUT}")


if __name__ == "__main__":
    main()
