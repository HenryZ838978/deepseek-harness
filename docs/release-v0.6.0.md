# deepseek-harness-cli 0.6.0

**Eleventh probe: `P11-plugin-inventory-manifest`.** `@deepseek-ai/dsh` 0.1.2-rc.1 (2026-09-03) is the first release to put the default-on `dsh_plugin_packages` request field under `latest`. That field throws when an active plugin's nearest `package.json` has a `name` and no `version` — and the manifest dsh writes into every profile it creates is exactly that shape.

```bash
pip install -U deepseek-harness-cli
dsh doctor --node --only P11-plugin-inventory-manifest
```

## What P11 reports

- **FAIL** — a relative plugin entry (`name: ./plugin.js`) in a profile's `cordis.patch.yml` resolves to a manifest the inventory rejects (dsh's own `~/.dsh/profiles/<name>/package.json`, or any name-without-version / BOM-prefixed manifest). Every `deepseek-official` request in that profile fails `REQUEST_EXTENSION` before HTTP, after the user turn was appended.
- **WARN** — profile manifests carry the rejected shape but no relative entry reaches them yet. One line away.
- **PASS** — inventory disabled by patch, or manifests carry `name` + `version` and no rejected entries.
- **SKIP** — no `$DSH_HOME/profiles`.

Evidence (`--json`) cites `plugin-package-inventory-deepseek/src/index.ts:66` (source) and `lib/index.js:34` (npm artifact), `llm-deepseek/src/adapter.ts:628`, `core/agent-loop/src/agent.ts:292 → :364`, and `boot/app-boot/src/profile.ts:205-210`. Full chain in the probe docstring and in [HISTORY.md](../HISTORY.md) under the rc.1 entry.

## Also in this release

- README P10 row no longer says "the sqlite backend does re-check" — that backend was removed in 0.1.2-alpha.3.
- Six new tests for P11 (33 total). No other probe's logic changed. All eight previously open defects re-verified present on the rc.1 source tag and on the compiled npm artifacts; P3 remains fixed.

## Upstream state at this release

`@deepseek-ai/dsh` dist-tags: `latest` = `next` = `0.1.2-rc.1`, `alpha` = `0.1.2-alpha.5`. rc.1 is alpha.5 with the version string changed (`diff -rq` on the two source trees, excluding `package.json` and i18n mirrors, returns nothing). alpha.5's one topic — the projection-cache read-compat fix that un-bricked 0.1.1-rc.2 → alpha.4 upgrades — is recorded in HISTORY as fixed in-release, independently observed.
