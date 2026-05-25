# 鲸伴 DeepSeek Harness — Mobile PWA

Zero-build Progressive Web App chat client for the DeepSeek Harness backend.
Plain HTML + ES modules + CSS. No bundler. `open public/index.html` runs it
locally; uploading `public/` + `src/` to any static host (nginx / Cloudflare /
Aliyun OSS / Vercel) deploys it.

Target: non-technical Chinese mobile users on iPhone / Pixel-class Android,
opened from WeChat scan or "添加到主屏幕".

## Layout

```
mobile-pwa/
├── README.md              # this file
├── public/
│   ├── index.html         # SPA shell — loads ../src/app.js as ES module
│   ├── manifest.json      # PWA manifest (name, theme, icons)
│   ├── sw.js              # service worker (cache-first shell, network /v1)
│   ├── icon-192.png       # ⚠️ TODO — generate (see below)
│   └── icon-512.png       # ⚠️ TODO — generate (see below)
└── src/
    ├── app.js             # router + service worker registration
    ├── api.js             # fetch wrapper, SSE streamRun, healthCheck
    ├── util.js            # toast, escape, markdown, long-press, cache
    ├── ui-login.js        # phone + OTP screen
    ├── ui-chat.js         # message list, composer, model picker
    ├── ui-sessions.js     # left drawer with past sessions
    └── styles.css         # mobile-first CSS, light + dark, safe-area
```

## Run locally

```bash
cd packages/mobile-pwa
python3 -m http.server 8000 --directory .
# open http://localhost:8000/public/index.html
```

The `index.html` references `../src/*.js` and `../src/styles.css` with relative
paths, so serving from the package root (one level above `public/`) works
without any symlinks. If you prefer to serve only `public/`, add a symlink:

```bash
ln -s ../src public/src
python3 -m http.server 8000 --directory public
# open http://localhost:8000/
```

## Configuring the backend

By default the PWA talks to `http://localhost:7777`. To point it at a different
backend (e.g. cloud), open the browser devtools console once and run:

```js
localStorage.setItem('BACKEND_URL', 'https://api.deepseek-harness.dev');
location.reload();
```

A settings UI for this will land in v2.

## Demo mode (no backend required)

The login screen accepts the mock OTP `123456` when the backend can't be
reached, and stores a dummy token. The chat screen will then load with the
"无法连接服务器" banner shown and history empty until a real backend is wired
up. This is intentional so the app can be demoed on a phone with no network
plumbing.

## Deploy

Upload `public/` and `src/` to any static host. Recommended:

- nginx: drop both folders into the doc-root; ensure `/sw.js` is served from
  the site root (or adjust the `scope` in the SW registration).
- Cloudflare Pages / Vercel: set the project root to `packages/mobile-pwa`,
  no build command, output directory `.`.
- Aliyun OSS + CDN: same — pure static.

CORS / TLS: the backend must allow the PWA's origin in `DSH_ALLOWED_ORIGINS`
(see `docs/consumer/API.md`). On iOS, the service worker only registers from
HTTPS or `localhost`.

## TODOs left for the user

1. **Generate PWA icons** — `public/icon-192.png` and `public/icon-512.png`
   are referenced in `manifest.json` and the Apple touch-icon link but do not
   exist yet. Generate a 1024×1024 master from the brand "深" glyph on the
   `#0EA5E9` background, then export 192 and 512 PNGs (consider a maskable-
   safe-area variant). Quick path: pwa-asset-generator or any design tool.
2. Add a real settings sheet for switching backend URL / logging out other
   devices.
3. Wire up image / file attachment upload in the composer (API already supports
   `attachments[]`).
4. Replace the demo `mock.demo.token` flow with a feature flag once the real
   SMS-issued JWT path is live.

## What's intentionally not here (per spec)

- No build step. No bundler. No npm install.
- No markdown library — see the 60-line renderer in `src/util.js`.
- No SMS / OTP backend — server-side concern.
- No payment / subscription UI.
- No i18n — strings are hardcoded Simplified Chinese.
