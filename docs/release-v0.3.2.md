# deepseek-harness-cli 0.3.2

One new probe for **`@deepseek-ai/dsh` rc.2** — the version promoted to `latest`.

```bash
pip install -U deepseek-harness-cli
export DEEPSEEK_API_KEY=sk-...
dsh doctor --node
```

## What's new

- **P9-files-quota-scope** *(new)*. rc.2 ships the DeepSeek Files API upload path with a `reclaimOldestOwned` recovery step that deletes remote /files entries whose filename starts with `OWNED_FILE_PREFIX = 'dsh-'`. The prefix is ecosystem-wide, not per-install. Two dsh installs sharing one API key each maintain a private local `~/.dsh/llm-deepseek/files-v3.json` but hit the same remote quota — when A reclaims, B's tracked file_ids get deleted, B's next image request hits "unknown file_id", B's prefix cache misses. This probe reads the local upload-index and warns whenever it has tracked records, listing scope hashes so you can spot cross-install collisions. Offline; no key.

## Not fixed here (still on the list)

- P2 · P3 · P4 · P5 · P6 · P7 · P8 all still present at `dsh-v0.1.1-rc.2`. rc.1 → rc.2 was 35 commits, almost all image pipeline. Zero of the previous 8 defects touched.

## Also observed, not made into probes

Vision pipeline audit surfaced three things that are policy choices, not defects. Recorded in HISTORY.md so the map is complete: aggressive client-side downscale, no dsh-side tiling, no vision streaming prefill.
