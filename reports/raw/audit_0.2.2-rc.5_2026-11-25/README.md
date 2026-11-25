# 0.2.2-rc.5 audit — 2026-11-25, host zw10g0579 ("037")

- Official harness: `npm i -g @deepseek-ai/dsh@0.2.2-rc.5` under Node v24.22.3.
- `headless_session_events.ndjson` — `dsh headless --json` on a 2-row CSV task (answer 6); its session log is `session.v4.jsonl.zstd`.
- `doctor_node_run{1,2}.json` — `dsh doctor --node --json` from this repo against that install (run1 = before the P5/P8 zstd/bundle fixes, run2 = after).
- `p5_seeded_resume_upstream.txt` — the live session copied three times: one duplicated seq, one dropped seq, one untouched control. Each copy was re-framed the way upstream writes it (header frame, then event frame) and resumed with `dsh headless --session-id`. Upstream refuses dup/gap with `invalid committed event at line N: released v2 row M has seq gap`. P5 flags the same line with the same expected/got numbers, and the control resumes and answers `6`.
- Source trees used for grep: codeload tarballs of `dsh-v0.1.5-rc.1`, `dsh-v0.2.2-rc.5`, `dsh-v0.2.3-alpha.2`. For P4/P11, a single file was fetched at each tag from `raw.githubusercontent.com` to bisect the fix.
