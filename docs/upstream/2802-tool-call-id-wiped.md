# Draft reply — upstream Discussion #2802

> **状态:待发,不单发。** 与其余 7 条一起回复(#2725 / #2755 / #2573 / #2756 / #2674 / #2787 / #2798 / #2665)。
> #2756、#2787 若复现涉及用户凭据/数据破坏,先私下报官方再公开。
> 复现环境与判定词表见 [`../DEVLOG.md`](../DEVLOG.md) 2026-08-17 条目。

---

Confirmed on `0.1.0-rc.6` (npm `latest`). I isolated it to a single unguarded
assignment in the block assembler, and the fix is one line. One correction to the
original report: **the assembler only loses the `id`, not the `name`** — the
`name: null` you see in the log comes from a *second, independent* defect
upstream of it. Details and a runnable repro below.

## Root cause: `id` is overwritten without a guard, `name` is not

`packages/llm/llm/src/assembler.ts` (rc.5 source; identical in the rc.6 compiled
artifact), in `BlockAssembler.push`, `case 'tool-call-delta'`:

```ts
partial.toolCallId = chunk.id                      // ← no guard: an empty id overwrites a good one
if (chunk.name) partial.toolCallName = chunk.name  // ← guarded: an empty name is ignored
partial.toolCallArguments += chunk.argumentsDelta
```

The two adjacent fields are treated asymmetrically. `name` survives a blank
follow-up delta; `id` does not. So a stream whose first delta carries
`id`+`name` and whose later deltas carry `id: ""` assembles to an empty
`callId`, and the executor rejects the call.

## Repro (no API key, no network — drives the shipped `BlockAssembler` directly)

```js
import { BlockAssembler } from '@deepseek-ai/dsh-llm'

const run = (chunks) => {
  const a = new BlockAssembler()
  for (const c of chunks) a.push(c)
  return a.blocks().filter(b => b.type === 'tool-call')
}
```

Three cases, same shipped code path:

**A — the stream shape from this report** (first delta complete, later deltas `id: ""`)

```
tool-call  id=""  name="write"  args="{\"file_path\":\"hello.txt\"}"
>>> empty id → executor throws unknown tool ""
```

**B — control: later delta blanks BOTH `id` and `name`**

```
tool-call  id=""  name="bash"  args="{\"cmd\":\"ls\"}"
>>> id lost, name SURVIVED
```

B is the decisive one: with `name: ""` and `id: ""` arriving in the *same*
delta, `name` is preserved and `id` is destroyed. That isolates the defect to
the missing guard rather than to multi-delta streaming in general.

**C — control: later delta repeats the same `id`** (healthy stream)

```
tool-call  id="call_x"  name="bash"  args="{\"cmd\":\"ls\"}"
(intact)
```

## Fix

```diff
- partial.toolCallId = chunk.id
+ if (chunk.id) partial.toolCallId = chunk.id
```

This makes `id` behave like the `name` line directly beneath it. It is
sufficient to stop the `unknown tool ""` failure for streams that send the id
once, which is the common case.

## The second defect (why you also see `name: null`)

`packages/llm/llm-pi-ai/src/stream.ts`, `case 'toolcall_start'`, snapshots the
id/name **once** and caches them for every subsequent delta:

```ts
const partial = event.partial.content[event.contentIndex]
const id   = partial?.type === 'toolCall' ? partial.id   : ''
const name = partial?.type === 'toolCall' ? partial.name : ''
toolIds.set(event.contentIndex, { id, name })
```

If the partial has not been populated at `toolcall_start` time — normal when the
provider sends the name with the first argument delta — this caches
`{id: '', name: ''}` permanently. Every later `toolcall_delta` then emits
`id: CallId('')`, and `name` is dropped entirely by the
`known.name.length > 0` condition, which is what surfaces as `name: null` in
`session.jsonl.zstd`.

For contrast, `packages/llm/llm-deepseek/src/translate.ts` keeps this state
correctly — it updates `block.callId` / `block.name` whenever the provider sends
them (`if (call.id !== undefined) …`) and re-emits the remembered value on every
delta. The pi-ai path lacks that update step.

So the two defects compose: pi-ai supplies blank ids, and the assembler lets a
blank id win. Fixing the assembler line stops the user-visible breakage; fixing
`toolcall_start` to refresh its cache (rather than snapshot once) addresses the
source.

## Downstream effect

Once a call assembles with an empty name, the executor's `unknown tool ""` is
returned to the model, which retries, which re-enters the same streaming path,
which blanks the id again — an unbounded retry loop. That matches the
`repeat-tool-reminder ×5` / wasted-token behaviour in this thread and the loop
reported in #2722, and #2725 is the same defect reported independently.

## Suggested regression test

Assemble a tool call split across ≥2 deltas where only the first carries
`id`/`name`, and assert both survive. The B case above is a useful second
assertion: blanking a field in a later delta must not destroy an
already-established value, for `id` and `name` alike.
