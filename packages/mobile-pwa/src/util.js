// Small shared utilities: toast, escape, markdown, sessions cache, dom helpers.

export const $ = (sel, root = document) => root.querySelector(sel);

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(node.style, v);
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'html') node.innerHTML = v; // caller's responsibility — only used for pre-escaped md
    else if (k in node) node[k] = v;
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return node;
}

export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

// ---------- toast ----------
let toastTimer = null;
export function toast(msg, kind = '') {
  const root = $('#toast-root');
  if (!root) return;
  const t = el('div', { class: 'toast' + (kind ? ' ' + kind : '') }, String(msg));
  root.appendChild(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    t.style.opacity = '0';
    setTimeout(() => t.remove(), 200);
  }, 2200);
}

export async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    }
    toast('已复制', 'ok');
  } catch {
    toast('复制失败', 'err');
  }
}

// ---------- long-press ----------
export function attachLongPress(node, handler, ms = 500) {
  let timer = null;
  let moved = false;
  let sx = 0, sy = 0;
  const start = (x, y) => {
    moved = false; sx = x; sy = y;
    timer = setTimeout(() => { if (!moved) handler(); }, ms);
  };
  const move = (x, y) => {
    if (Math.abs(x - sx) > 8 || Math.abs(y - sy) > 8) { moved = true; clearTimeout(timer); }
  };
  const end = () => clearTimeout(timer);
  node.addEventListener('touchstart', (e) => start(e.touches[0].clientX, e.touches[0].clientY), { passive: true });
  node.addEventListener('touchmove',  (e) => move(e.touches[0].clientX, e.touches[0].clientY),  { passive: true });
  node.addEventListener('touchend', end);
  node.addEventListener('touchcancel', end);
  node.addEventListener('mousedown', (e) => start(e.clientX, e.clientY));
  node.addEventListener('mousemove', (e) => move(e.clientX, e.clientY));
  node.addEventListener('mouseup', end);
  node.addEventListener('mouseleave', end);
}

// ---------- minimal markdown -> HTML ----------
// Supports: fenced code ```lang\n...\n```, inline `code`, **bold**, *italic*, [text](url), paragraphs.
// Output is safe: all text is escaped first, then a controlled set of markers is replaced.
export function renderMarkdown(src) {
  const text = String(src ?? '');
  const blocks = [];
  // Pull fenced code blocks out first so their content isn't escaped twice / formatted.
  const stripped = text.replace(/```([\w+-]*)\n([\s\S]*?)```/g, (_, lang, body) => {
    const i = blocks.push({ lang: lang || '', body }) - 1;
    return `\u0000CODE${i}\u0000`;
  });

  // Escape everything else.
  let html = escapeHtml(stripped);

  // Inline code.
  html = html.replace(/`([^`\n]+)`/g, (_, c) => `<code>${c}</code>`);
  // Links [text](url) — url restricted to http(s)/mailto.
  html = html.replace(/\[([^\]]+)\]\(((?:https?:|mailto:)[^)\s]+)\)/g,
    (_, t, u) => `<a href="${u}" target="_blank" rel="noopener noreferrer">${t}</a>`);
  // Bold then italic.
  html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');

  // Paragraphs from blank-line splits.
  html = html
    .split(/\n{2,}/)
    .map((p) => p.trim() ? `<p>${p.replace(/\n/g, '<br>')}</p>` : '')
    .join('');

  // Put code blocks back in (with copy button placeholder).
  html = html.replace(/\u0000CODE(\d+)\u0000/g, (_, i) => {
    const b = blocks[+i];
    return `<pre><button class="copy-code-btn" data-copy="1">复制</button><code>${escapeHtml(b.body)}</code></pre>`;
  });

  return html;
}

// Wires up the copy buttons inside an element rendered from renderMarkdown.
export function wireCopyButtons(root) {
  root.querySelectorAll('button[data-copy]').forEach((btn) => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const pre = btn.closest('pre');
      const code = pre && pre.querySelector('code');
      if (code) copyText(code.textContent || '');
    });
  });
}

// ---------- session transcript cache (localStorage) ----------
const TX_KEY = 'dsh.tx.';
export function saveTranscript(id, msgs) {
  try { localStorage.setItem(TX_KEY + id, JSON.stringify(msgs.slice(-200))); } catch {}
}
export function loadTranscript(id) {
  try { return JSON.parse(localStorage.getItem(TX_KEY + id) || '[]'); } catch { return []; }
}
export function cacheSessions(list) {
  try { localStorage.setItem('dsh.sessions', JSON.stringify(list || [])); } catch {}
}
export function cachedSessions() {
  try { return JSON.parse(localStorage.getItem('dsh.sessions') || '[]'); } catch { return []; }
}
