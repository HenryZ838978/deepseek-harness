// Left-edge slide drawer listing past sessions.

import { el, toast } from './util.js';
import { listSessions, deleteSession } from './api.js';
import { cacheSessions, cachedSessions } from './util.js';

// Returns an open(true|false) function so the caller (chat header) can toggle.
export function renderSessionsDrawer(host, { getActiveId, onPick, onNew, onLogout }) {
  const backdrop = el('div', { class: 'drawer-backdrop', onClick: () => open(false) });
  const list = el('div', { class: 'drawer-list' });
  const closeBtn = el('button', { class: 'icon-btn', 'aria-label': '关闭', onClick: () => open(false) }, '✕');
  const newBtn = el('button', { onClick: () => { onNew(); open(false); } }, '＋ 新对话');
  const logoutBtn = el('button', { onClick: onLogout }, '退出登录');

  const drawer = el('aside', { class: 'drawer' },
    el('div', { class: 'drawer-header' }, el('b', {}, '历史会话'), closeBtn),
    list,
    el('div', { class: 'drawer-foot' }, newBtn, logoutBtn),
  );

  host.appendChild(backdrop);
  host.appendChild(drawer);

  // edge-swipe to open
  let touchStartX = null;
  document.addEventListener('touchstart', (e) => {
    if (drawer.classList.contains('open')) return;
    const x = e.touches[0].clientX;
    if (x < 16) touchStartX = x;
  }, { passive: true });
  document.addEventListener('touchend', (e) => {
    if (touchStartX == null) return;
    const dx = e.changedTouches[0].clientX - touchStartX;
    if (dx > 48) open(true);
    touchStartX = null;
  });

  function renderList(items) {
    list.innerHTML = '';
    if (!items || !items.length) {
      list.appendChild(el('div', { class: 'drawer-empty' }, '还没有会话，开始第一段对话吧。'));
      return;
    }
    const activeId = getActiveId();
    for (const s of items) {
      const item = el('button', {
        class: 'drawer-item' + (s.id === activeId ? ' active' : ''),
        onClick: () => { onPick(s); open(false); },
      },
        el('b', {}, s.title || '未命名会话'),
        el('small', {}, [
          s.model || 'auto',
          ' · ',
          formatWhen(s.last_active),
          typeof s.cost_usd_total === 'number' ? ` · ¥${s.cost_usd_total.toFixed(2)}` : '',
        ].join('')),
      );
      list.appendChild(item);
    }
  }

  async function refresh() {
    renderList(cachedSessions());
    try {
      const items = await listSessions();
      cacheSessions(items);
      renderList(items);
    } catch {
      // keep cached view
    }
  }

  function open(show) {
    drawer.classList.toggle('open', !!show);
    backdrop.classList.toggle('open', !!show);
    if (show) refresh();
  }

  return open;
}

function formatWhen(ts) {
  if (!ts) return '';
  const d = new Date(typeof ts === 'number' && ts < 1e12 ? ts * 1000 : ts);
  if (Number.isNaN(d.getTime())) return '';
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) return d.toTimeString().slice(0, 5);
  return (d.getMonth() + 1) + '月' + d.getDate() + '日';
}
