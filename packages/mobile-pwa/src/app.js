// Entry point — routes between login and chat based on localStorage `token`.

import { renderLogin } from './ui-login.js';
import { renderChat } from './ui-chat.js';

const root = document.getElementById('app');

export function navigate(to) {
  root.innerHTML = '';
  if (to === 'chat') renderChat(root, { navigate });
  else renderLogin(root, { navigate });
}

function boot() {
  const hasToken = !!localStorage.getItem('token');
  navigate(hasToken ? 'chat' : 'login');
}

// Hot-route on token change in another tab.
window.addEventListener('storage', (e) => {
  if (e.key === 'token') boot();
});

// Register service worker (best-effort).
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('./sw.js', { scope: './' })
      .catch(() => {}); // SW is optional; ignore failures (e.g. file:// origins).
  });
}

boot();
