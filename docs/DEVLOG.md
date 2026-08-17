# deepseek-harness (Python) — Dev Log

> 本仓 = 官方 Node 框架 `deepseek-ai/deepseek-harness` 的 **Python 侧见证栈**。
> 战略定调见 musicodec [`docs/DEVLOG.md`](../../musicodec/docs/DEVLOG.md) 2026-08-17 条目;
> 纯事实时间线待建 `PROVENANCE.md`。单条时间线,倒序。

---
## 2026-08-17 (二·跨夜) — J3 #2571 **REPRODUCED,双失败模式** + P5 探针 + 上游底稿

### 硬结论

**#2571 端到端复现,并把病灶推大一档:seq gap 有两种失败模式,原报告只见其一。**

| 输入模式(seq 序列)                     | scanLog 行为 | 语义 |
|---|---|---|
| `0,1,2` 健康                              | ok, 3 events | baseline |
| `0,1,1` / `0,1,3` / `0,1,0` / `0,1,1,2`  | **不 throw**,events 停在 gap 前 | **静默截断** — session 加载,但内容少了,用户看不出 |
| `0,1,1,turn/end@2` / `0,1,end@1` / `0,1,0,end@1`  | **THROW** `corrupt session log: seq gap ...` | session **永久不可加载** |

关键代码位置(rc.6 编译产物 `dsh-session-persistence-jsonl/lib/index.js:281–293`,
对应源 `format.ts` 的 `SessionLogScanner.consumeEventLine`):

```js
if (event.seq !== this.events.length) {
  ...
  this.issue = new Error(`corrupt session log: seq gap ...`)
  if (decoded.some(c => c.type === "turn/end")) throw this.issue
  return                                                          // 否则暗藏
}
```

`this.issue` 是**惰性引爆的地雷**——任何后续行只要带 `turn/end` 就 throw。
正常会话结束都会写 turn/end,所以**两个 concurrent writer 各自完成一个 turn 就百分百炸**。

### 为什么持久化层拦不住

- `link()+unlink()` 发布(`index.ts:544–546`)只防**已发布产物被覆盖**,防不了两个进程各自 `open()` 追加。
- `PersistenceCoordinator.state.owner`(`coordinator.ts:940`)是**进程内**排他,跨进程各自 `owner === undefined` 都 attach。
- `grep -rE 'flock|O_EXCL|lockf|proper-lockfile' packages/session/` → **命中 0**。
  **进程内不变量被当成系统不变量**——不是一回事。

### 方法学(J3 用哪种复现)

尝试 A:两个 Node 进程真起 Session/JsonlSessionPersistence → Cordis Service 需要 ctx,依赖太重,弃。
尝试 B(采用):**忠实移植 scanLog 到独立 mjs**(源码就 30 行),喂手工构造的 JSONL fixture。
scanner 是纯函数,fixture 就是 concurrent writer 会落盘的字节 —— 等价证明。
无 API 调用、~2s CPU、零成本。

### 产出(commit 就绪)

- `packages/cli/deepseek_harness_cli/doctor_node/p5_seqgap.py` —— **P5-seqgap 探针**,
  离线扫用户 session dir 的 `.jsonl`,两种模式各自报告(FAIL/WARN),`.jsonl.zstd` 暂缓(需 zstd 解码)。
  验证:合成 corrupt/truncated fixture → 正确检出 FAIL 与 WARN。
- `docs/upstream/DRAFT-2571-concurrent-writers.md` —— **正式底稿**,含双模式说明、代码位置、修复建议(`flock(LOCK_EX|LOCK_NB)` on log fd)。**标注"先私下、5 工作日不回再公开"**。
- `docs/upstream/2802-tool-call-id-wiped.md` 顶部加 **STALE — DO NOT SEND** 前言,防日后误发。
- 服务器 `overnight/j3/notes.md` + `scan_probe.json` —— 完整 trial matrix,归档在服务器 dsh-probe/。

### J1(P1 长采样)预告观察 —— 跨夜跑 200 trials

截跑到 95/200 时的**信号非常清晰**,非随机:

- `single_tool` prompt 组:几乎全线 `total≈14 / reasoning=0`(silent)
- `multi_tool` 组:大多 healthy(`reasoning=100+`),偶发 silent
- silence 与 **prompt 短小/简单** 强相关

即"reasoner+tools 吞 reasoning_content" **不是随机现象,是有触发条件的**——
最可能是短提示让 reasoner 快速给答案,skip 掉 reasoning stream 阶段。
待 200 trials 完再定完整假设,`overnight/j1/summary.json` 会有相关矩阵。

### 跨夜执行栈(记录以便复盘)

- 本机 `caffeinate -dimsu` 前台守护
- 服务器 `setsid nohup env DEEPSEEK_API_KEY=... N_PER_CELL=10 ./runall.sh &`
- `overnight/runall.sh` 串行 J1(采样)→J2(dsh-toolkit 侦察)→J3(re-freshen scan)
- 各 job 独立 log 在 `overnight/logs/`,汇总 `overnight/SUMMARY.md`
- key 只在 env 传递,脚本内不落盘、日志内经 sed 擦除

### 明早 wake 后 checklist

1. `tail overnight/j1/summary.json`——看 silence rate 按 prompt/temp 的分布是否稳定
2. 读 `overnight/j2/recon.md`——决 dsh-toolkit 撞车姿态(合流/分岔)
3. 读 `overnight/j3/notes.md`——已完成,只需 confirm 没被 J3 re-run 弄乱
4. **本地 commit(不 push)**:P5 + DRAFT-2571 + DEVLOG 本条目 + 2802 STALE 标记
5. 更新 README:「what dsh doctor sees today」section 加 P5
6. 决 push 时机:等 J1 完 + 底稿定稿再一次性 push

---
## 2026-08-17 (二·夜) — `dsh doctor --node` v0 上线 + 元插件占位

### 一句话

**用他们自己的"一切皆插件"审判他们**:`dsh doctor --node` 四探针(P1–P4)骨架落地,
外加 `@deepseek-harness/dsh-doctor-plugin` Node shim 占位——插件形态挂在官方运行时上,
里面的合约逻辑委托给 Python 侧的 `dsh doctor --node`。

### 探针清单(v0)

| id | 覆盖 | 依赖 | 出场 |
|---|---|---|---|
| **P1-reasoner-wire** | reasoner+tools 时 `reasoning_content` 是否被吞(N 轮采样) | `DEEPSEEK_API_KEY` | 本次独家发现 + 命中 README 三件事之首 |
| **P2-bom** | 本机插件 `package.json` 是否带 UTF-8 BOM | 离线 | #2798 |
| **P3-serve** | `dsh web` 跨源 Origin 是否被 fence 拦(loopback vs 非-loopback) | 需活 dsh web | #2573 |
| **P4-spill** | subprocess spill 目录是否可写(`spillAll` 无 try/catch 会 exit 1) | 离线 | 勇哥⑥ |

代码:`packages/cli/deepseek_harness_cli/doctor_node/{__init__.py, runner.py, p1..p4}`。
CLI:`dsh doctor --node [--json] [--only P1,P2] [--url URL]`。
四态输出:PASS/WARN/FAIL/SKIP,rich 表 + `--json` 双格式,一个 probe 崩不会带走 runner。

### 元插件

`packages/dsh-doctor-plugin/` — Node package(`@deepseek-harness/dsh-doctor-plugin`)。
package.json 的 `dsh.kind = "meta-plugin"`,`bin/dsh-doctor.mjs` spawn `python3 -m deepseek_harness_cli doctor --node`。
测过 Node shim → Python doctor 全链路(P2+P4 组合),PASS/SKIP 都对。
**姿态明确**:这不是给官方运行时加能力的插件,而是给它做审计的插件——它的存在本身即评论。

### P1 的方法论坑(必须记)

本机第一次跑 P1:`12 tc frames / 0 reasoning frames` → FAIL。
紧接第二次:`12 tc frames / 17 reasoning frames` → PASS。
两次背对背、同 prompt、同模型、同 key,判定翻转。

**订正上午条目**:上午写「244 帧无一 `reasoning_content`」当作 wire 稳定态是**过强**——
它是一次采样,真实上游是**间歇性**silence(intermittent silence),非常态失败。

**P1 因此改为 N 轮采样(默认 3),分档报告**:
- silent > 0 且 healthy = 0  → FAIL(强证据:每次都被吞)
- silent > 0 且 healthy > 0  → WARN(间歇性,production harness 必须做防御)
- silent = 0 且 healthy > 0  → PASS
- 全部无 tool_calls           → WARN(inconclusive)

3 轮实测:同一 prompt 分别 (25,22,22) reasoning / (12,12,12) tc,silent=0 → PASS。
本地当前样本量下**无法证明**"reasoner+tools 系统性吞 reasoning_content"这一强命题;
能证明的只有:**间歇性 silence 存在,官方 Node 侧无任何防御**。上游稿相应降调。

原则加进仓的运作:**任何 wire 侧探针,一次投票不下判**。

### 挂载点决策

现有 `dsh doctor`(API 侧体检)保留原语义。`--node` 走新层,靶点从"我这条链好不好"变为"官方 Node 栈那条链有没有系统性洞"。
`dsh doctor --node` 定位不与 #2801 `dsh-toolkit` 竞争:后者做工具集,我们只做见证/审计——
撞车问题在明天读它源码后再定。

### 排队

- P1 需扩到 ≥10 轮采样才敢下"系统性"判(留 v0.1);
- P5 起草:#2571 并发 seq gap(必须真复现);
- P6 起草:#2653 大会话历史加载 RangeError(离线检测 session 大小/嵌套即可);
- `dsh doctor --node --advise` 模式:检出后自动出上游 issue 底稿。

---
## 2026-08-17 (二·晚) — 端到端真流式:**#2802 判定反转,不进上游稿**

### 反转结论

用 DS 官方 key 走 `https://api.deepseek.com/chat/completions` 真流式,并在 rc.6 产物内
让 `DeepSeekAdapter.stream()` → `BlockAssembler.push()` 完整跑一遍 —— **`unknown tool ""` 无法端到端复现。**

| 观测面 | 样本 | `id:""` | `name:""` | 结果 block 坏 |
|---|---|---|---|---|
| 上游 raw SSE(`curl` 直连,三轮) | 301 帧 `tool_calls` | **0** | **0** | — |
| 端到端(adapter+assembler,四轮) | 1275 帧 `tool-call-delta` | **0** | **0** | **0 / 6 blocks** |

### 因果订正

早些时候把 2802 认作"一行缺陷 assembler.ts:70 无守卫",证据是**手工构造 delta**(`t2802.mjs` A/B/C 组)。
这一步的静态因果仍然成立(70 无守卫、71 有守卫,不对称是事实),但**其对外可触发性依赖上游发出 `id:""`**。
今晚实测:

- **DeepSeek 上游对 tool-call 采用"首帧全量、后续 delta 只发 `arguments`"**——`id` / `function.name` 字段在后续帧**根本不出现**(`absent`,非空串);
- llm-deepseek `translate.ts:159` 的守卫 `if (call.id !== undefined) block.callId = call.id` **正好挡住 `absent`**,`block.callId` 保留首帧好值;
- 再传给 assembler 的每帧 `tool-call-delta.id` 都是同一个好值,`:70` 冲写等价 no-op。

**结论**:2802 在**当前 DS 上游行为下不可触发**。上游 issue 稿(`docs/upstream/2802-tool-call-id-wiped.md`)不发。
`assembler.ts:70` 守卫不对称仍是内部代码洞,值得提 PR,但不能挂"end-user visible bug"标签。

### 复现资产(留档)

`live/req.json / req2.json / req3.json`(三份请求体);`live/sse.raw / sse2.raw / sse3.raw`(原始 SSE);
`globaltest/t2802_live.mjs / t2802_live2.mjs`(端到端探针,rc.6 产物,通过 `DS_KEY` env 传密钥,
代码内不落 key,SSE 返回体不含 key,擦除后无残留)。

### 顺带一条真实缺陷(值得单独进上游稿)

`deepseek-reasoner` + `tool_choice:"required"` 直接返回 `HTTP 400: "Thinking mode does not support this tool_choice"`。
把 tool_choice 改为 `"auto"` 后,244 帧全流程 `reasoning_content` **一帧不出**——**思考模式带 tools 时,思维链在 wire 上被吞**。
这正好击中 README/roadmap 第一件事「reasoning_content 回传」和 `dsh doctor` 前三嫌疑之一(路由轮思考税)。
另开条目:`docs/upstream/reasoner-tools-no-reasoning-content.md`(待写),这一条**先私下报官方,一周不回再公开**。

### 反转带来的方法论修正

- **手工 delta 探针 ≠ 端到端复现**。今后 DEVLOG 里凡挂"复现,定位到行"标签的条目,
  必须包含一条真上游 → adapter → assembler 全链路的可执行证明,否则降级为"静态代码洞"。
- 见证栈的信用不靠"抓到 bug 数量"堆,靠**订正自己**的速度。今晚这一步就是仓的第一块信用砖。
- `dsh doctor` 的 2802 探针从「检查 tool-call id 完整性」改为「回归监测 DS 上游 tool-call 帧协议
  是否改变(未来若上游改成发空串,DSH 侧立刻中招)」——变**当前无害的静态洞**为**面向未来的哨兵**。

### 排队待补

- `#2571 concurrent writers seq gap` 尚未真复现(上一轮结构性排除只对单进程内存 append 成立);
- `long args 500+ chars` 案例出现 1172 帧 tc-delta 但 `tool_blocks=0` —— assembler 状态机在无 finish 标记时不 emit tool-call 块,是否会影响 session persist 需单独查;
- `docs/upstream/2802-*.md` 需改标题为「静态代码洞:守卫不对称」并附本条订正链接。

---
## 2026-08-17 (二) — 官方 Discussions 全量账本 + 第二轮严肃复现

### 为什么换来源

第一轮的讽刺文章是**戏谑吐槽**,只能当线索。正经需求来源应为**带编号的公开条目**。
但官方仓 `has_issues: false`、`pulls` API 404(外部 PR 不收,#2674 报告人原话:
"Since external PRs are not accepted at the moment"),**Issues 与 PR 双关**。
唯一开放入口是 Discussions。

一度误判"issue 墙不存在"——那是只查了 REST `has_issues` 没查 Discussions 网页所致。
**订正:issue 墙存在,规模巨大,只是搬进了一个不产生问责记录的容器。**

### 全量账本(匿名可爬,无需凭据)

爬 112 页触底,解析 `disc/ledger.json`:

| 指标 | 值 |
|---|---|
| 总条目 | **2,773**(编号 13–2804) |
| 疑似缺陷(关键词命中) | **899(32%)** |
| 其中**零回复** | **864(占缺陷 96%)** |
| 最高回复的缺陷帖 | **7 回**(#2564) |
| 对照:闲聊帖 #1728「加群送插件」 | **75 回** |
| 分类 | general 1261 / show-your-plugins 645 / ideas 545 / q-a 311 / polls 5 |

Discussions 与 Issues 的差别不是形式:issue 有状态机(open/closed/label/assign)、
能被 commit 自动关闭、可检索交叉引用;discussion 都没有。
**结论(仅陈述可证事实):缺陷是收的,问责记录是不留的。**
配合 npm/GitHub 双侧 `modified` 均停在 2026-08-13T12:36Z、首发后零提交零修复。

### 版本流水(npm registry,公开)

| 版本 | 时间 |
|---|---|
| 0.0.1-rc.1 | **2026-08-10T19:41Z** |
| 0.0.1-rc.2 / rc.5 | 08-11 / 08-12 |
| 0.1.0-rc.2 / rc.3 / **rc.6** | 08-13 同日三发 |

**8/10 首次发包 = 对方索要 PyPI 名的同一天**:是在已备好发包的状态下来要名字的。
rc.2→rc.3→rc.6 结构 diff:依赖数恒为 61,零增删,第三方依赖零变化,
唯一实质改动是 `publishConfig.access` 由 `restricted` → `public`。
**三个 rc 是发布流程本身,不是修 bug。**

### 第二轮复现结论(判定词表同上)

| # | 条目 | 判定 | 依据 |
|---|---|---|---|
| **2802 / 2725 / 2674** | 流式 delta 丢 tool name/id → `unknown tool ""` | **复现,定位到行** | 见下 |
| **2798** | 带 BOM 的 package.json 直接 `JSON.parse` 崩 | **确认,证据即代码** | rc.6 产物 `dsh-app-boot/lib/index.js:453` 与 **548 两处**裸 parse;全文件 `feff/stripBOM` 命中 **0** |
| **2573** | 非 loopback origin 前端数据层静默不启动 | **复现,补全因果** | 见下 |
| **2755** | 思维链泄漏进可见 content | **DSH 侧主张确认** | `packages/llm/` 下 `<think>/</think>/unclosed/dangling` 命中 **0**——不是"难以区分",是**未尝试区分** |
| 2756 | apikey 泄露 | **无法判定,不列** | 正文仅"额度-4、凌晨在跑",无日志/版本/配置/网络证据;"泄露"是用户推断非观测 |
| 2787 | 清空他人会话历史 | **非官方行为,不列** | `session.jsonl.zstd` 与 `sessions--X--` 目录形态在 rc.6 产物中不存在(官方为 `session.jsonl`),指向第三方插件/fork |
| 2665 | dshbase 551/351 验证报告 | **来源已被作者撤回,不列** | 该帖正文实为道歉:"内部初版验证数据和正式数据混在一起…人工审核失误",报告移出官方仓 |

**不列的三条是主动排除**:证据不足或非官方行为的条目混入,会拉低整份报告可信度,
而可信度是本仓唯一资产。宁少勿滥。

### 2802:一行缺陷,name 有守卫而 id 没有

`packages/llm/llm/src/assembler.ts` `case 'tool-call-delta'`:

```ts
partial.toolCallId = chunk.id                      // ← 无守卫,空串冲掉好值
if (chunk.name) partial.toolCallName = chunk.name  // ← 有守卫 ← 相邻两行,不对称
```

用官方导出的 `BlockAssembler` 直接喂三组 delta(无需 API key):

| 组 | 输入 | 输出 |
|---|---|---|
| A | 首帧带 id+name,后续帧 `id:""` | `id="" name="write"` → `unknown tool ""` |
| B | 后续帧 **同时**给 `id:"" name:""` | `id=""` 而 **`name="bash"` 存活** |
| C | 后续帧带回同一 id | 完好 |

**B 是决定性的**:同一帧里 name 被守住、id 被摧毁,把缺陷锁死在"缺守卫",
排除"多帧流式本身有问题"。一行修复:`if (chunk.id) partial.toolCallId = chunk.id`。

**订正原报告**:assembler 只丢 id,**name 是保住的**;日志里的 `name: null` 来自
另一处独立缺陷 `llm-pi-ai/src/stream.ts` —— `toolcall_start` 对 id/name **只快照一次**,
读空即永久缓存空值。对照 `llm-deepseek/src/translate.ts` 有 sticky 更新,写法正确。
**两处独立缺陷叠加**,只修 assembler 那一行即可挡住绝大多数发作。

后果按三份报告升级:空 `callId` 被持久化 → 重载时 `assertMessageEventShape` 拒读 →
`SessionPersistenceCorruptionError`(#2725 seq 55 / #2674 seq 1077)→ **会话历史永久不可加载**。
不是"工具调用失败",是**数据损坏**。#2674 已在 fork 修完三处并附 101 通过测试,
请求 cherry-pick,四天无回应。

### 2573:静态资源不过闸,API 过闸 → 静默空转

本地起 rc.6 `dsh web` 实测:

| | loopback Host | 非 loopback Host |
|---|---|---|
| `GET /`(HTML+JS) | 200 | **200** ← 页面照发 |
| `host.describe` | 404(路由名不符,但**过了信任闸**) | **403** |
| `/api/events.mux` 升级 | **101** | **403** |

机制:前端资源无条件下发 → 插件 JS 全部加载 → 一建数据层即被 403 →
拿到的是连接层失败而非应用层错误 → **无 console 报错、主线程空闲、永停「选择工作区」**。
报告人每条观察都对上,并解释了他未解释的"激活在 connection.start 之前中止"。

**性质**:这不是 bug,是 fence 按设计生效。真正的缺陷是**失败模式**——
该给降级提示,却给了静默空转。与第一轮线索① 是同一 fence 的两副面孔
(① 为两种 loopback 拼写不一致 → 403,缺别名等价)。

### 需订正的自测结论

**#2571「Session log corruption from concurrent writers — seq gap in commit」**
与第一轮线索⑤ 撞题。我方⑤ 判"结构性排除"仅对**单进程内存 `Session.append`** 成立;
#2571 指向**持久化提交层的多写者并发**,未测。
**⑤ 结论加限定,#2571 另立复现项**,不得含糊带过。

### 排队中的高价值条目(尚未复现)

#2675 compaction 忽略输出预算 / #2571 并发写 seq gap / #2737 中文长会话 compaction thrashing /
#2653 大会话 `RangeError: Maximum call stack size exceeded` / #2727 三条生命周期路径致历史不可加载 /
#2751 用户明着要 `dsh doctor` / #2781 workspace-write 下 pwsh 派生死锁。

### 对 roadmap 的影响

- **#2755 正中本仓靶心**:README 三件事之首即 reasoning_content 回传,官方 Node 侧对此**零防御**。
  Python 侧做「可算出 misroute 率的探针」是直接可用的差异化(vllm #48645 实测 20-25% misroute)。
- **#2751 已有用户公开索要 `dsh doctor`**;#2801 已有第三方 dsh-toolkit 在做 —— 需求被确认,坑未占死。
- **#2787 的副产品**:用户分不清官方行为与插件行为。`dsh doctor` 应列出实际加载的插件及
  其对持久化路径的改写。
- 插件 conformance 验证器立论**不再引用 351 这个数字**(已撤回),改引可证事实:
  官方对 1800+ 插件的一致性**不做任何背书**,社区自建口径混乱且被劝退出官方仓。

### 上游回复稿

`docs/upstream/2802-tool-call-id-wiped.md`(待发)。**八条齐了一起发,不单发**——
主动权在我方。#2756/#2787 类涉用户凭据/数据破坏的条目若日后复现,
**先私下报官方再公开**:公开时序上留一手,反使见证栈信用更硬。

---
## 2026-08-17 — 官方 DSH 首轮探针:六条线索复现

### 线索来源与其效力

一篇中文讽刺长文(「勇哥说软件」)列举官方 DSH 六条缺陷。该文**戏谑吐槽,密度高但不严肃**,
在本仓的地位仅为**线索**(lead),不构成需求来源:

- 所有判定必须引本次自测的原始输出,**不引文章**;
- 判定词表统一为 **复现 / 未复现 / 无法判定**;
- 需求来源另定:官方 discussion / issue 墙上**带编号**的正经条目(见「下一步」)。

### 测试基线(不耍赖)

远端 `zhangjing:/cache/zhangjing/dsh-probe/`(1.3 GB):

| 项 | 取值 |
|---|---|
| 源码 | `master` 分支 tarball,`0.1.0-rc.5` |
| 已装产物 | `npm i @deepseek-ai/dsh@0.1.0-rc.6` |
| Node | 22.19.0(专为满足 `engines: ^22.19.0 \|\| >=24` 而装,杜绝"环境不合规"抗辩) |
| 协议 | Anthropic Messages,`https://api.deepseek.com/anthropic/v1`,`x-api-key` + `anthropic-version: 2023-06-01` |
| 启动方式 | README 自己写的 `npx @deepseek-ai/dsh web` 与 `http://127.0.0.1:3080` |

关键取舍:⑥ 的判定跑在**已编译的 rc.6 产物**上(`node_modules/@deepseek-ai/dsh-subprocess-local/lib/index.js`),
即用户实际执行的字节,而非源码;且经由官方导出的 `LocalSubprocessRuntime` 正常 `spawn` 触发,
不直接构造内部类。

### 结论表

| # | 线索 | 判定 | 依据 |
|---|---|---|---|
| ① | 默认地址 `127.0.0.1:3080` 选工作区 403,换 `localhost` 好 | **部分复现,因果相反** | README 的地址返回 **200**。403 只在 Host 与 Origin 用**不同 loopback 写法**时触发 |
| ② | 全局装需 100+ 插件包,仅约半数可解析 | **未复现** | rc.6:532 包 / 196 个 `@deepseek-ai/*` / 0 个 `ERR!` / `npm ls` exit 0 / `dsh --version` 正常 / `dsh web` 起得来 |
| ③ | `workspace-write` 下模型可够到控制面并自批提权 | **复现,且官方已自认** | 见下 |
| ④ | 外部副作用已生效的工具被迟到的 cancel 记成 ABORTED | **未复现,方向相反** | 已开始的记 `TOOL_OUTCOME_UNKNOWN`,未开始的记 `TOOL_NOT_STARTED`;无 tool-result 级 ABORTED |
| ⑤ | 中断+恢复后两写者发重复 `seq` → 判 session 损坏 | **未复现,结构性排除** | `seq = log.length` 派生,写者无从自报 |
| ⑥ | spill 落盘失败使异常逃出回调打死整个 Harness | **复现** | `spillAll()` 两处 IO 无 try/catch,进程 exit 1 |

六条中两条实锤(③⑥)、一条方向被推翻(①)、三条不成立(②④⑤)。

### ① 因果被推翻

`packages/client/connection/src/loopback-hostname.ts` 认 `localhost ≡ 127.x ≡ [::1]`;
但 `api-request-trust.ts` 的 Origin 闸做**字面串比**:

```ts
return new URL(origin).host === hostUrl.host   // 无 loopback 别名等价
```

故 403 的真实触发条件是 Host 与 Origin 拼写不一致,而非"用了 `127.0.0.1`"。
安全侧正确:`evil.com` / `Origin: null` / `sec-fetch-site: cross-site` 均被拒。
**缺的是别名等价,不是安全洞。**

### ③ 是设计取舍,不是疏忽

- `docs/subsystems/sandbox.md:11`:`SandboxMode` **只管文件系统**,"Network and process
  visibility are outside this vocabulary";
- `/api/respond` 不在 `PRIVILEGED_METHODS` 内,只有 schema 校验,无主体校验;
- `api-proxy.ts:1408-1425`:mux 重连会**以相同 rpcId 重放待批帧**,重连方可得知待批 rpcId。

对照实验:无凭据自 loopback 调特权方法 `settings.describe` → `ok:true, writable:true`;
同一请求带 `Host: evil.com` → 403。即"特权"实际只等于"在 loopback 上",而模型的 bash 就在 loopback 上。

官方注释原话已自认该性质:

> the deployment's own default already carries `bash` and the filesystem tools, so any caller
> that may start a session at all can already run commands as this process.
> **Pinning the switch would be a fence beside an open gate.**

该 fence 自述 "explicitly not authentication"。**属已知取舍,非缺陷**。

### ④/⑤ 方向相反:恢复语义比文章设想的更保守

`packages/core/session/src/repair.ts` 把中断的调用**按是否已记录开始**分两档:

| 情形 | code | 给模型的话 |
|---|---|---|
| 已记 `tool/call`(副作用可能已生效) | `TOOL_OUTCOME_UNKNOWN` | 结果未知;**有副作用就先核实外部状态或问用户,不要盲目重试** |
| 未记(从未开始) | `TOOL_NOT_STARTED` | 仍需要就重试 |

恰是文章担心的语义混淆的**反面**。

`seq` 由 `index.ts:629` 的 `seq: this.log.length` 派生;seed 校验拒绝重复与空洞
(`seed must be contiguous from 0`);`append` 有重入闸
(`session append cannot reenter while another append is being published`);
对已修复日志重跑 `interruptedTurnClosers` 补 0 条(幂等)。⑤ 在这套 API 下**无法表达**。

### ⑥ 唯一的纯代码缺陷

`packages/subprocess/subprocess-local/src/spawn.ts`(rc.6 编译产物 `lib/index.js` ~393/417 同构):

```ts
private spillAll(chunk: Buffer): void {
  if (this.spillFd === undefined) {
    this.spillFile = join(this.spillDir, `dsh-subprocess-...log`)
    this.spillFd = openSync(this.spillFile, 'wx', 0o600)   // ← 无 try/catch
    for (const prior of this.chunks) writeSync(this.spillFd, prior)
  }
  writeSync(this.spillFd, chunk)                            // ← 无 try/catch
}
private discardSpill(): void {
  ... try { closeSync(fd) } catch { this.spillFd = fd }     // ← 隔壁两处 IO 都守了
  ... try { unlinkSync(file) } catch { }
}
```

调用点同样裸奔:`stream.on('data', (chunk) => { collector.push(chunk) })`(`spawn.ts:366`)。
全文件 10 处 try/catch,无一覆盖此路径。

实测(spill 目录 chmod 500):

```
>>> uncaughtException 逃出 data 回调 <<<
    code    : EACCES  syscall: open
    stack[0]: at openSync (node:fs:561:18)
    stack[1]: at OutputCollector.spillAll (.../lib/index.js:417:19)
    stack[2]: at OutputCollector.push  (.../lib/index.js:393:75)
```

去掉自装 handler(即真实 Harness 处境)→ Node 默认 handler → **exit 1**。
可写目录对照组 → exit 0。

同一文件里 `discardSpill` 守了而 `spillAll` 没守,这个**不对称**基本可判定为遗漏,够格作为 upstream issue。

### 探针资产

`t1/`(① 决策表) `t4.mjs`(④ 恢复语义) `t5.mjs`(⑤ seq 攻击面) `t6d/e/f.mjs`(⑥ 故障注入 + 对照组)。
解法会过期,探针不过期 —— 按 roadmap 第 2 层,这批应并入 `dsh audit` 的回归集。

### 踩过的环境坑(复现者须知)

- MCP shell 工具 ~100s 硬超时 → 一切等待改 `setsid nohup` + 非阻塞快照轮询;
- `pkill -f <pattern>` 会匹配到发起命令自身 → 自杀;
- 该宿主机 **HTTP/2 大传输到 GitHub 必断**(`stream 1 was not closed cleanly`),
  git pack 卡在 ~116K;`codeload` tarball 走 `--http1.1` 13.7 MB / <30s 通过;
- 默认分支是 `master` 不是 `main`(codeload 404 的原因);
- `node --experimental-strip-types` 解析不了 TS **构造器参数属性** → 改用编译产物(反而更贴近用户);
- 工具在 `/bin/sh` 下跑,`${PIPESTATUS[0]}` 不可用。

### 下一步(**不进解法代码**)

文章的价值到此为止。进代码前必须先有正经需求来源:

1. 爬官方 discussion / issue 墙,**只取带编号条目**,建需求账本;
2. 对选中的 issue 做严肃复现(同上基线、同上判定词表),复现通过才进我方代码;
3. ⑥ 另走 upstream issue 底稿(与我方 `dsh doctor` 的 spill 目录可写性预检互不阻塞)。

> issue 墙是免费 roadmap:官方替我们做了需求筛选与优先级排序,且每条都带可引用的编号。
