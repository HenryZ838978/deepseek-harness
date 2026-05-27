// Main chat screen.

import { $, el, toast, attachLongPress, copyText, renderMarkdown, wireCopyButtons,
         saveTranscript, loadTranscript } from './util.js';
import { streamRun, getBudget, cancel as apiCancel, healthCheck, getSession } from './api.js';
import { renderSessionsDrawer } from './ui-sessions.js';

const MODELS = [
  { id: 'auto',   name: '自动',    desc: '让鲸伴自动选择' },
  { id: 'flash',  name: 'Flash',  desc: '极速 · 适合日常对话' },
  { id: 'pro',    name: 'Pro',    desc: '更强 · 适合代码与推理' },
  { id: 'pro-1m', name: 'Pro 1M', desc: '超长上下文 · 1M tokens' },
];

const MODEL_BADGE = { auto: '自动', flash: 'Flash', pro: 'Pro', 'pro-1m': 'Pro 1M' };

export function renderChat(root, { navigate }) {
  const state = {
    sessionId: null,
    sessionTitle: '新对话',
    messages: [],            // { role, text, dom, mode? }
    model: localStorage.getItem('model') || 'auto',
    streaming: null,         // { controller, agent } when active
    budget: null,
    online: true,
  };

  // ---- header ----
  const hamburger = el('button', { class: 'icon-btn', 'aria-label': '会话列表' }, '☰');
  const titleB = el('b', {}, state.sessionTitle);
  const titleSub = el('small', {}, 'DeepSeek Harness');
  const modelBadge = el('button', { class: 'model-badge', 'aria-label': '切换模型' },
    MODEL_BADGE[state.model] || '自动', ' ▾');
  const budgetPill = el('div', { class: 'budget-pill' }, '今日 ¥— / ¥—');

  const header = el('div', { class: 'chat-header' },
    hamburger,
    el('div', { class: 'chat-title' }, titleB, titleSub),
    modelBadge,
    budgetPill,
  );

  const banner = el('div', { class: 'banner', hidden: true }, '无法连接服务器，已切换到离线浏览模式');

  // ---- message list ----
  const msgList = el('div', { class: 'msg-list' });
  const emptyState = el('div', { class: 'msg-empty' },
    el('b', {}, '你好 👋'),
    '说点什么开始吧。鲸伴可以帮你写代码、读文档、改 Bug。',
  );
  msgList.appendChild(emptyState);

  // ---- composer ----
  const textarea = el('textarea', {
    placeholder: '发消息给鲸伴…',
    rows: 1,
    enterkeyhint: 'send',
  });
  textarea.addEventListener('input', () => {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, window.innerHeight * 0.3) + 'px';
    sendBtn.disabled = !textarea.value.trim();
  });
  textarea.addEventListener('keydown', (e) => {
    // Enter to send on desktop only — mobile shows a return key.
    if (e.key === 'Enter' && !e.shiftKey && !('ontouchstart' in window)) {
      e.preventDefault();
      onSend();
    }
  });

  const sendBtn = el('button', { class: 'send-btn', type: 'button', disabled: true }, '发送');
  const cancelBtn = el('button', { class: 'cancel-btn', type: 'button', hidden: true }, '取消');
  sendBtn.addEventListener('click', onSend);
  cancelBtn.addEventListener('click', onCancel);

  const composer = el('div', { class: 'composer' }, textarea, sendBtn, cancelBtn);

  // ---- drawer ----
  const drawerHost = el('div');
  const openDrawer = renderSessionsDrawer(drawerHost, {
    getActiveId: () => state.sessionId,
    onPick: (s) => loadSession(s),
    onNew:  () => startNewSession(),
    onLogout: () => {
      localStorage.removeItem('token');
      navigate('login');
    },
  });
  hamburger.addEventListener('click', () => openDrawer(true));

  // ---- model picker ----
  modelBadge.addEventListener('click', () => openModelSheet());

  // ---- assemble ----
  const wrap = el('div', { class: 'chat' }, header, banner, msgList, composer);
  root.appendChild(wrap);
  root.appendChild(drawerHost);

  // ---- side effects ----
  refreshBudget();
  pingHealth();

  // ===== handlers =====

  function setStreaming(on, agentMsg) {
    state.streaming = on ? { controller: on, agent: agentMsg } : null;
    sendBtn.hidden = !!on;
    cancelBtn.hidden = !on;
    textarea.disabled = !!on;
  }

  async function onSend() {
    const prompt = textarea.value.trim();
    if (!prompt || state.streaming) return;
    textarea.value = '';
    textarea.style.height = 'auto';
    sendBtn.disabled = true;

    if (emptyState.parentNode) emptyState.remove();

    const userMsg = pushMessage({ role: 'user', text: prompt });
    const agentMsg = pushMessage({ role: 'agent', text: '', thinking: '', tools: [] });
    scrollToBottom();

    const { controller, done } = streamRun(
      { prompt, sessionId: state.sessionId, model: state.model },
      (event, data) => handleEvent(event, data, agentMsg),
    );
    setStreaming(controller, agentMsg);

    try {
      await done;
    } finally {
      finalizeAgentBubble(agentMsg);
      setStreaming(null, null);
      sendBtn.disabled = !textarea.value.trim();
      persist();
    }
  }

  async function onCancel() {
    if (!state.streaming) return;
    const sid = state.sessionId;
    state.streaming.controller.abort();
    if (sid) {
      try { await apiCancel(sid); } catch {}
    }
    toast('已取消');
  }

  function handleEvent(event, data, agentMsg) {
    switch (event) {
      case 'session': {
        if (data.session_id && !state.sessionId) {
          state.sessionId = data.session_id;
        }
        break;
      }
      case 'delta': {
        if (typeof data.text === 'string') {
          agentMsg.text += data.text;
          agentMsg.streamSpan.textContent = agentMsg.text;
          scrollToBottom();
        }
        break;
      }
      case 'thinking': {
        if (typeof data.delta === 'string') {
          agentMsg.thinking = (agentMsg.thinking || '') + data.delta;
          ensureThinkingBlock(agentMsg);
          agentMsg.thinkingTextEl.textContent = agentMsg.thinking;
        }
        break;
      }
      case 'tool_call': {
        agentMsg.tools = agentMsg.tools || [];
        agentMsg.tools.push({ id: data.id, name: data.name });
        const chip = el('span', { class: 'tool-chip' }, '🔧 ' + (data.name || 'tool'));
        agentMsg.toolsEl.appendChild(chip);
        scrollToBottom();
        break;
      }
      case 'usage': {
        if (typeof data.cost_usd === 'number' && state.budget) {
          state.budget.today_usd = (state.budget.today_usd || 0) + data.cost_usd;
          renderBudget();
        }
        break;
      }
      case 'done': {
        if (data && typeof data.result === 'string' && !agentMsg.text) {
          agentMsg.text = data.result;
          agentMsg.streamSpan.textContent = data.result;
        }
        refreshBudget();
        break;
      }
      case 'error': {
        toast(friendlyRunError(data), 'err');
        agentMsg.text = agentMsg.text || ('⚠️ ' + (data.message || '出错了'));
        agentMsg.streamSpan.textContent = agentMsg.text;
        break;
      }
    }
  }

  function pushMessage(m) {
    const row = el('div', { class: 'bubble-row ' + m.role });
    const bubble = el('div', { class: 'bubble' });
    const streamSpan = el('div', { class: 'stream-text' }, m.text || '');
    const toolsEl = el('div');
    bubble.appendChild(streamSpan);
    if (m.role === 'agent') bubble.appendChild(toolsEl);
    row.appendChild(bubble);
    msgList.appendChild(row);

    const msg = { ...m, dom: row, bubble, streamSpan, toolsEl, thinkingTextEl: null };
    state.messages.push(msg);

    attachLongPress(bubble, () => copyText(msg.text || ''));
    return msg;
  }

  function ensureThinkingBlock(msg) {
    if (msg.thinkingEl) return;
    const block = el('details', { class: 'aux-block' },
      el('summary', {}, '💭 思考中...'),
    );
    const txt = el('div', { class: 'thinking-text' });
    block.appendChild(txt);
    msg.thinkingEl = block;
    msg.thinkingTextEl = txt;
    msg.bubble.insertBefore(block, msg.streamSpan);
  }

  function finalizeAgentBubble(msg) {
    if (msg.role !== 'agent') return;
    if (msg.thinkingEl) {
      msg.thinkingEl.querySelector('summary').textContent = '💭 思考过程';
      msg.thinkingEl.open = false;
    }
    if (msg.text) {
      const rendered = el('div');
      rendered.innerHTML = renderMarkdown(msg.text);
      wireCopyButtons(rendered);
      msg.streamSpan.replaceWith(rendered);
      msg.streamSpan = rendered;
    }
  }

  function scrollToBottom() {
    requestAnimationFrame(() => {
      msgList.scrollTop = msgList.scrollHeight;
    });
  }

  // ===== budget / health =====
  async function refreshBudget() {
    try {
      const b = await getBudget();
      state.budget = b;
      renderBudget();
    } catch {
      // leave placeholder values
    }
  }
  function renderBudget() {
    const b = state.budget;
    if (!b) { budgetPill.textContent = '今日 ¥— / ¥—'; return; }
    const today = (b.today_usd ?? 0).toFixed(2);
    const cap   = (b.cap_usd   ?? 0).toFixed(2);
    budgetPill.textContent = `今日 ¥${today} / ¥${cap}`;
    budgetPill.classList.toggle('over', (b.today_usd ?? 0) >= (b.cap_usd ?? 0));
  }

  async function pingHealth() {
    const ok = await healthCheck();
    state.online = ok;
    banner.hidden = ok;
  }

  // ===== sessions =====
  function startNewSession() {
    state.sessionId = null;
    state.sessionTitle = '新对话';
    titleB.textContent = state.sessionTitle;
    state.messages = [];
    msgList.innerHTML = '';
    msgList.appendChild(emptyState);
  }

  async function loadSession(s) {
    state.sessionId = s.id;
    state.sessionTitle = s.title || '会话';
    titleB.textContent = state.sessionTitle;
    state.messages = [];
    msgList.innerHTML = '';

    let transcript = loadTranscript(s.id);
    try {
      const full = await getSession(s.id);
      if (full && Array.isArray(full.messages)) {
        transcript = full.messages.map((m) => ({
          role: m.role === 'user' ? 'user' : 'agent',
          text: m.text || '',
        }));
      }
    } catch {
      if (!transcript.length) {
        toast('无法加载远程会话，已显示离线缓存', 'err');
      }
    }

    if (!transcript.length) {
      msgList.appendChild(emptyState);
      return;
    }
    for (const m of transcript) {
      const msg = pushMessage(m);
      if (msg.role === 'agent') finalizeAgentBubble(msg);
    }
    scrollToBottom();
  }

  function persist() {
    if (!state.sessionId) return;
    saveTranscript(state.sessionId,
      state.messages.map((m) => ({ role: m.role, text: m.text })));
  }

  // ===== model picker =====
  function openModelSheet() {
    const sheet = el('div', { class: 'sheet' },
      el('h4', {}, '选择模型'),
      ...MODELS.map((m) =>
        el('button', {
          class: 'sheet-opt' + (m.id === state.model ? ' chosen' : ''),
          onClick: () => {
            state.model = m.id;
            localStorage.setItem('model', m.id);
            modelBadge.firstChild.nodeValue = MODEL_BADGE[m.id] || m.name;
            close();
          },
        },
          el('span', {}, m.name),
          el('small', {}, m.desc),
        ),
      ),
      el('button', { class: 'sheet-opt', onClick: () => close() },
        el('span', { style: { color: 'var(--ink-muted)' } }, '取消'),
      ),
    );
    const backdrop = el('div', { class: 'sheet-backdrop', onClick: (e) => { if (e.target === backdrop) close(); } }, sheet);
    document.body.appendChild(backdrop);
    function close() { backdrop.remove(); }
  }
}

function friendlyRunError(d) {
  const code = d && d.code;
  if (code === 'budget_exceeded') return '今日额度已用完，请明天再试或调高上限';
  if (code === 'model_unavailable') return '模型暂时不可用，请稍后重试';
  if (code === 'auth_expired') {
    localStorage.removeItem('token');
    return '登录已过期，请重新登录';
  }
  if (code === 'agent_crash') return '助手意外退出';
  return (d && d.message) || '发生错误';
}
