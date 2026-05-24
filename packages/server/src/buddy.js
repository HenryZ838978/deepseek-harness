// Buddy Layer — turn DeepSeek V4 Pro into a non-technical user's "super buddy".
//
// Three jobs:
//   1. System prompt that bans jargon (脚本/路径/JSON/终端/sudo/cli/...) and
//      replaces with friendly Chinese ("我帮你写个小程序", "您的文件" …).
//   2. Context injection — file index + device-self-check snapshot the Mac
//      client gathered and POSTed up. The agent never has to ask "what's the
//      path of your Excel file" because the index already mapped it.
//   3. Light post-processing of agent's final reply: rewrite any technical
//      term that slipped past the prompt.
//
// All of this is gated by mode === "buddy" on /v1/run. Developer-facing
// requests (mode omitted or "dev") bypass everything.

export const BUDDY_SYSTEM_PROMPT = `你是用户的私人电脑助理"深求"，性格温暖、主动、像一个住在 Mac 里的好朋友。用户是完全不懂技术的普通人。

【你必须遵守的说话方式】
1. 永远说人话，绝对禁止出现这些词：脚本 / 路径 / 命令 / 终端 / sudo / 代码 / JSON / 目录 / 文件夹 / shell / bash / CLI / API / npm / 仓库 / git / 端口 / 进程 / 内核
2. 必须换成：
   - "脚本/代码/小程序" → "小工具" 或 "我写个小东西帮你"
   - "路径" → "您的文件" 或 "桌面上那个 XX"
   - "终端/命令" → "我去帮您操作一下"
   - "目录/文件夹" → "您电脑里的 XX 那一摊东西"
   - "API/JSON/接口" → "网上的数据"
   - "进程/内核" → "电脑正在跑的某个东西"
3. 谈到具体文件，永远用《书名号》包住名字，不要给完整路径。例如说"您桌面上的《年度报告.docx》"，不说"/Users/xx/Desktop/年度报告.docx"。
4. 谈到 App，用中文名：微信、飞书、钉钉、WPS、Chrome 浏览器、QQ 邮箱。不说 com.tencent.xinWeChat 这种内部名字。
5. 长度控制：每次回复最多 3 段。第一段说"我打算做什么"（一句话），中间做事，最后一段说"做完了 + 结果是什么 + 您要不要继续"。不要长篇大论。
6. 永远主动给两到三个下一步建议，让用户用点的，不要让他打字想。

【你被允许做的事】
- 直接读取、修改、移动用户的文件，不需要询问（除非是删除超过 5 个文件、清空回收站、修改系统设置这类危险操作）
- 自动决定工作目录（用户从来不需要知道工作目录是什么）
- 自动安装小工具（如果需要 Python 包之类，背着用户装，不要让他看见 pip install）
- 自动重试失败的操作 3 次
- 自动整理、归类、命名用户文件，告诉他结果

【你必须先问一句再做的事】
- 删除任何文件（哪怕一个）
- 给任何人发消息、发邮件、发文件
- 修改系统设置（音量、亮度、网络除外，这些可以直接调）
- 关闭超过 3 个软件
- 清理浏览器数据、缓存
- 一切动用密码、支付、登录的事

【遇到错误时怎么办】
- 不要把英文报错原文丢给用户
- 翻译成一句中文，比如 "网络好像不太稳定，我再试一次" 或 "这个文件好像被某个软件占着，您要不要先把 Word 关掉？"
- 失败 3 次再告诉用户，前两次自己悄悄重试

【对话开场】
- 用户启动我或新开会话时，先用 1 句话主动招呼，提 1-2 个可点击的建议
- 不要问"请问您要做什么？"——太被动；要主动猜
- 例：「下午好！您电脑现在挺顺畅的。要不要我帮您把桌面整理一下？或者继续昨天没看完的《项目周报》？」

【自我介绍】
当被问到"你是谁" / "你是什么模型"时：
"我是您电脑里的'深求'助手，由深度求索的 V4-Pro 模型驱动。可以把我当成一个住在 Mac 里、不睡觉的小助手。"
绝对不要说"我是 Claude"或"我是 GPT"或"我是 AI 大模型"。
`;

/**
 * Wrap a user prompt with buddy system prompt + injected context.
 *
 * @param {string} userPrompt - what the user typed
 * @param {object} context - optional context block from the Mac client:
 *   {
 *     device: {              // BootScan.swift snapshot
 *       model, ram_gb, free_gb_pct, temp, chrome_tab_count, …
 *     },
 *     recent_files: [        // FileIndex.swift snapshot
 *       { app: "WeChat",  name: "项目周报.docx",   modified: "2026-05-20" },
 *       { app: "Feishu",  name: "Q3-OKR.sheet",   modified: "2026-05-22" },
 *       …
 *     ],
 *     greeting: true,        // first message of a session — agent should greet
 *     user_name: "小李",
 *   }
 * @returns {string} preamble + userPrompt to send to claude
 */
export function wrapBuddyPrompt(userPrompt, context = {}) {
  const lines = [];
  lines.push("<SYSTEM_BUDDY_RULES>");
  lines.push(BUDDY_SYSTEM_PROMPT);
  lines.push("</SYSTEM_BUDDY_RULES>");
  lines.push("");

  if (context.user_name) {
    lines.push(`<USER>${context.user_name}</USER>`);
  }
  if (context.device) {
    lines.push("<DEVICE_SNAPSHOT>");
    lines.push(formatDevice(context.device));
    lines.push("</DEVICE_SNAPSHOT>");
  }
  if (context.recent_files && context.recent_files.length) {
    lines.push("<RECENT_FILES>");
    lines.push("以下是用户最近用过的文件，遇到提到文件的请求直接从这里找，不要问用户路径：");
    for (const f of context.recent_files.slice(0, 200)) {
      lines.push(`  · 《${f.name}》（${f.app}，${f.modified || "近期"}）→ ${f.full_path || ""}`);
    }
    lines.push("</RECENT_FILES>");
  }
  if (context.greeting) {
    lines.push("");
    lines.push("【这是这次会话的第一句对话】请按系统规则主动招呼用户、给出 1-2 个可点击的建议，然后等用户回应。");
  }

  lines.push("");
  lines.push("<USER_REQUEST>");
  lines.push(userPrompt || "(用户没说话，请主动打招呼。)");
  lines.push("</USER_REQUEST>");

  return lines.join("\n");
}

function formatDevice(d) {
  const parts = [];
  if (d.model) parts.push(`型号：${d.model}`);
  if (d.cpu)   parts.push(`芯片：${d.cpu}`);
  if (d.ram_gb !== undefined) parts.push(`内存：${d.ram_gb}GB（已用${d.ram_used_pct ?? "?"}%）`);
  if (d.disk_total_gb !== undefined) {
    parts.push(`存储：${d.disk_total_gb}GB（剩${d.disk_free_gb ?? "?"}GB / ${d.disk_free_pct ?? "?"}%）`);
  }
  if (d.cpu_load !== undefined) parts.push(`CPU 占用：${d.cpu_load}%`);
  if (d.battery_pct !== undefined) parts.push(`电量：${d.battery_pct}%${d.charging ? "（充电中）" : ""}`);
  if (d.chrome_tab_count !== undefined) parts.push(`Chrome 打开标签数：${d.chrome_tab_count}`);
  if (d.running_apps_count !== undefined) parts.push(`正在运行的软件数：${d.running_apps_count}`);
  if (d.uptime_hours !== undefined) parts.push(`开机时长：${d.uptime_hours} 小时`);
  if (d.network) parts.push(`网络：${d.network}`);
  if (d.warnings && d.warnings.length) parts.push(`异常：${d.warnings.join("；")}`);
  return parts.join("\n");
}

// ---- Output post-processing ----
// Lightweight safety net for jargon that slips past the system prompt.
// Keep this small — over-rewriting destroys meaning. Only catch the most
// common offenders that scare non-technical users.
const REWRITES = [
  // path-shaped strings → "您的文件"
  [/\/Users\/[^\s,，。)）"']+/g, "您的文件"],
  [/~\/[A-Za-z0-9_./-]+/g, "您的文件"],
  // command words → friendly
  [/\b(?:bash|zsh|shell|terminal|console)\b/gi, "我的小工具"],
  [/\b(?:sudo|chmod|chown)\s+\S+/g, "提升一下权限"],
  [/\bAPI\b/g, "网上的数据接口"],
  [/\bJSON\b/g, "结构化数据"],
  [/\bnpm install\s+(\S+)/g, "安装一下 $1 这个小组件"],
  [/\bpip install\s+(\S+)/g, "安装一下 $1 这个小组件"],
  // 文件夹 → "您电脑里的XX"
  [/\b文件夹\b/g, "文件夹"],   // keep — "文件夹" is fine, non-technical
];
export function postProcess(text) {
  if (!text) return text;
  let out = text;
  for (const [re, sub] of REWRITES) out = out.replace(re, sub);
  return out;
}

export function isBuddyMode(req) {
  return req && req.mode === "buddy";
}
