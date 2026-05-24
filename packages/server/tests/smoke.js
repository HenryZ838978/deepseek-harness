// Smoke test. Run after `node bin/dsh-server.js` is up on :7777.
// Verifies: /health, /v1/budget (none-mode auth), /v1/run end-to-end SSE.

import { request } from "node:http";

const HOST = "127.0.0.1", PORT = 7777;

function call(method, path, { body, headers, stream } = {}) {
  return new Promise((resolve, reject) => {
    const opts = { host: HOST, port: PORT, method, path, headers: { ...(headers || {}) } };
    if (body) {
      opts.headers["content-type"] = "application/json";
      opts.headers["content-length"] = Buffer.byteLength(body);
    }
    const req = request(opts, res => {
      if (stream) return resolve(res);
      let buf = "";
      res.on("data", c => buf += c);
      res.on("end", () => resolve({ status: res.statusCode, body: buf }));
    });
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

async function main() {
  const tests = [];
  function ok(name, cond, detail = "") {
    tests.push({ name, ok: !!cond, detail });
    console.log(`${cond ? "✓" : "✗"} ${name}${detail ? "  " + detail : ""}`);
  }

  // 1. /health
  const h = await call("GET", "/health");
  const hj = JSON.parse(h.body);
  ok("/health 200 + ok", h.status === 200 && hj.ok === true, `version=${hj.version}`);
  ok("/health reports anthropic key", hj.has_anthropic_key === true,
     hj.has_anthropic_key ? "" : "ANTHROPIC_AUTH_TOKEN / DEEPSEEK_API_KEY not set in env or env.sh!");

  // 2. /v1/budget (none-mode → no auth needed)
  const b = await call("GET", "/v1/budget");
  const bj = JSON.parse(b.body);
  ok("/v1/budget 200", b.status === 200, `today=$${bj.today_usd} cap=$${bj.cap_usd}`);

  // 3. /v1/run end-to-end (only if key present)
  if (hj.has_anthropic_key) {
    console.log("\n--- /v1/run streaming test (≈10–30 s) ---");
    const res = await call("POST", "/v1/run", {
      stream: true,
      body: JSON.stringify({ prompt: "Say the single word 'pong' and nothing else.", model: "flash" }),
    });
    const events = [];
    let answer = "";
    let buf = "";
    await new Promise((resolve, reject) => {
      res.on("data", chunk => {
        buf += chunk.toString();
        const frames = buf.split("\n\n");
        buf = frames.pop();
        for (const frame of frames) {
          const ev = frame.match(/^event:\s*(.+)$/m);
          const da = frame.match(/^data:\s*(.+)$/m);
          if (!ev || !da) continue;
          let data; try { data = JSON.parse(da[1]); } catch { continue; }
          events.push({ event: ev[1], data });
          if (ev[1] === "delta") answer += data.text || "";
          if (ev[1] === "done" || ev[1] === "error") resolve();
        }
      });
      res.on("end", resolve);
      res.on("error", reject);
      setTimeout(() => { console.log("(timeout 60s)"); resolve(); }, 60_000);
    });
    const types = new Set(events.map(e => e.event));
    console.log("event types seen:", [...types].join(", "));
    console.log("answer:", JSON.stringify(answer.slice(0, 200)));
    ok("/v1/run got 'session' frame", types.has("session"));
    ok("/v1/run got 'done' or 'error'", types.has("done") || types.has("error"));
    if (types.has("error")) {
      const err = events.find(e => e.event === "error");
      console.log("ERROR DETAIL:", err.data);
    }
    ok("/v1/run produced text", answer.length > 0, `(got ${answer.length} chars)`);
  } else {
    console.log("⚠  skipping /v1/run test — no API key configured");
  }

  const passed = tests.filter(t => t.ok).length;
  console.log(`\n${passed}/${tests.length} passed`);
  process.exit(passed === tests.length ? 0 : 1);
}

main().catch(e => { console.error(e); process.exit(1); });
