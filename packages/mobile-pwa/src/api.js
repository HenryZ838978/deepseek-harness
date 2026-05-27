// Thin fetch wrapper for the DeepSeek Harness backend.
// Endpoints documented in docs/consumer/API.md.

const DEFAULT_BACKEND = 'http://localhost:7777';

export function getBackend() {
  try {
    return localStorage.getItem('BACKEND_URL') || DEFAULT_BACKEND;
  } catch {
    return DEFAULT_BACKEND;
  }
}

export function setBackend(url) {
  localStorage.setItem('BACKEND_URL', url);
}

function authHeaders() {
  const t = localStorage.getItem('token');
  return t ? { Authorization: 'Bearer ' + t } : {};
}

async function jsonRequest(method, path, body) {
  const res = await fetch(getBackend() + path, {
    method,
    headers: {
      'content-type': 'application/json',
      ...authHeaders(),
    },
    body: body == null ? undefined : JSON.stringify(body),
  });
  let data = null;
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('json')) {
    try { data = await res.json(); } catch {}
  }
  if (!res.ok) {
    const err = (data && data.error) || { code: 'http_' + res.status, message: res.statusText };
    throw Object.assign(new Error(err.message || 'request failed'), { code: err.code, status: res.status, hint: err.hint });
  }
  return data;
}

// ----- auth -----
export async function sendOTP(phone) {
  return jsonRequest('POST', '/v1/auth/otp', { phone });
}

export async function login(phone, otp) {
  return jsonRequest('POST', '/v1/auth/login', { phone, otp });
}

// ----- sessions / budget -----
export async function listSessions() {
  return jsonRequest('GET', '/v1/sessions');
}

export async function getSession(id) {
  return jsonRequest('GET', '/v1/sessions/' + encodeURIComponent(id));
}

export async function deleteSession(id) {
  return jsonRequest('DELETE', '/v1/sessions/' + encodeURIComponent(id));
}

export async function getBudget() {
  return jsonRequest('GET', '/v1/budget');
}

export async function cancel(sessionId) {
  return jsonRequest('POST', '/v1/cancel/' + encodeURIComponent(sessionId));
}

// ----- streaming /v1/run -----
// onEvent(eventName, dataObj). Returns { controller, done } where `done` is a
// promise that resolves when the stream terminates (or rejects on transport error).
export function streamRun({ prompt, sessionId, model = 'auto', workspace = 'default', attachments }, onEvent) {
  const controller = new AbortController();
  const body = {
    prompt,
    model,
    workspace,
    permission_mode: 'bypassPermissions',
  };
  if (sessionId) body.session_id = sessionId;
  if (attachments && attachments.length) body.attachments = attachments;

  const done = (async () => {
    let res;
    try {
      res = await fetch(getBackend() + '/v1/run', {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          accept: 'text/event-stream',
          ...authHeaders(),
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (e) {
      if (e.name === 'AbortError') return;
      throw e;
    }

    if (!res.ok || !res.body) {
      let payload = null;
      try { payload = await res.json(); } catch {}
      const err = (payload && payload.error) || { code: 'http_' + res.status, message: res.statusText };
      onEvent('error', err);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    try {
      while (true) {
        const { done: rdDone, value } = await reader.read();
        if (rdDone) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf('\n\n')) !== -1) {
          const raw = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          parseSSEFrame(raw, onEvent);
        }
      }
      if (buf.trim()) parseSSEFrame(buf, onEvent);
    } catch (e) {
      if (e.name === 'AbortError') return;
      onEvent('error', { code: 'network', message: e.message || '连接中断' });
    }
  })();

  return { controller, done };
}

function parseSSEFrame(raw, onEvent) {
  let name = 'message';
  let data = '';
  for (const line of raw.split('\n')) {
    if (!line || line.startsWith(':')) continue;
    if (line.startsWith('event:')) name = line.slice(6).trim();
    else if (line.startsWith('data:')) data += (data ? '\n' : '') + line.slice(5).replace(/^ /, '');
  }
  if (!data) return;
  let payload;
  try { payload = JSON.parse(data); } catch { payload = { raw: data }; }
  try { onEvent(name, payload); } catch {}
}

// Quick health check used to show the "无法连接服务器" banner.
export async function healthCheck() {
  try {
    const res = await fetch(getBackend() + '/health', { method: 'GET' });
    return res.ok;
  } catch {
    return false;
  }
}
