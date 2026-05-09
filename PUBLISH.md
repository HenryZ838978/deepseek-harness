# Publishing checklist · `deepseek-harness`

> 给 Henry 的逐步指令。验证状态 2026-05-09：
> - PyPI 名字 `deepseek-harness` 和 `deepseek-harness-cli` **可用** (404 on PyPI)
> - npm 名字 `@deepseek-harness/mcp` **可用** (404 on registry)
> - 本地 `python -m build` × 2 通过、`twine check` 全 PASSED、`npm pack --dry-run` 干净

---

## 0 · 一次性准备（10 分钟）

### 0.1 PyPI 账号 + API token

1. 注册 https://pypi.org → Verify 邮箱
2. 设置 2FA（2024 年起 PyPI 强制要求）
3. https://pypi.org/manage/account/token/ → **Add API token** → Scope = "Entire account"（首次发布只能选 Entire；之后回来改成 per-project）
4. 复制 `pypi-AgEI...` 的 token，**离开页面就再也看不到**
5. 写到 `~/.pypirc`：

```ini
# ~/.pypirc
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-AgEIxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-AgEIxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

`chmod 600 ~/.pypirc`

### 0.2 npm 账号 + 自动 publish 权限

1. 注册 https://www.npmjs.com → Verify 邮箱 + 启用 2FA
2. 命令行登录：`/tmp/npm-wrap login` (或 `npm login` 如果系统装了 npm)
3. 创建 organization 来 host scoped 包：
   - 浏览器开 https://www.npmjs.com/org/create
   - Org name = `deepseek-harness` （与 scope `@deepseek-harness/...` 一致）
   - Plan = Free（公开包 free，private 才付费）
4. （可选）拿 Granular Access Token，写到 `~/.npmrc`：
   ```ini
   //registry.npmjs.org/:_authToken=npm_xxxxxxxxxxxxx
   ```
   chmod 600 `~/.npmrc`

### 0.3 GitHub repo (推荐先建)

虽然 PyPI / npm 不强制，但所有 metadata 已经 hard-code 了 `https://github.com/HenryZ838978/deepseek-harness`。建议先建 repo：

```bash
cd /cache/zhangjing/deepseek-harness
git init
git add -A && git commit -m "0.2.0 initial release: 4-form harness for DeepSeek V4"
gh repo create HenryZ838978/deepseek-harness --public --source=. --push --description "Harness for DeepSeek V4-Pro / V4-Flash. Python lib + dsh CLI + MCP server + Anthropic Skill."
```

---

## 1 · PyPI 发布（5 分钟）

### 1.1 推荐先走 TestPyPI 验证

```bash
cd /cache/zhangjing/deepseek-harness

# build (artifacts already exist, but re-build is cheap)
( cd packages/core && rm -rf dist && python -m build )
( cd packages/cli  && rm -rf dist && python -m build )

# upload to TestPyPI first
python -m twine upload --repository testpypi packages/core/dist/* packages/cli/dist/*

# verify install from TestPyPI
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            deepseek-harness deepseek-harness-cli
dsh doctor      # should print the green table
```

### 1.2 真正发布

```bash
python -m twine upload packages/core/dist/* packages/cli/dist/*
```

如果 token 是 per-project scope (after first publish you should switch to it)，命令变成：

```bash
TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-PROJECT-SCOPED-TOKEN \
  python -m twine upload packages/core/dist/*

TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-PROJECT-SCOPED-TOKEN \
  python -m twine upload packages/cli/dist/*
```

### 1.3 发布后立即验证

```bash
pip install -U deepseek-harness deepseek-harness-cli
dsh version          # 0.2.0
dsh doctor           # 绿表
```

PyPI URL 立刻可用：
- https://pypi.org/project/deepseek-harness/
- https://pypi.org/project/deepseek-harness-cli/

---

## 2 · npm 发布（5 分钟）

### 2.1 dry-run 一次（已验证过，复发就省略）

```bash
cd /cache/zhangjing/deepseek-harness/packages/mcp
npm install         # 如果 node_modules 没了
npm run build       # 必须先 build，否则 dist/ 不存在
npm pack --dry-run  # 看 tarball 内容
```

期望输出：6 个文件 (`dist/index.js`, `dist/safe_call.js`, 两个 `.d.ts`, `package.json`, `README.md`)，总 ~7.3 kB。

### 2.2 真正发布

```bash
cd /cache/zhangjing/deepseek-harness/packages/mcp

# scoped package + 公开访问 必须显式 --access public
npm publish --access public

# 触发 2FA OTP（如果 npm account 启用了 2FA）
# Enter OTP from your authenticator: 123456
```

### 2.3 发布后立即验证

```bash
# 任意目录：
DEEPSEEK_API_KEY=sk-... npx -y @deepseek-harness/mcp 2>&1 | head -3
# 期望: [deepseek-harness-mcp] ready · 4 tools · v0.2.0
# (npx 自己会 install 然后 run, 第一次需要约 10 秒下载)

# 再来一发 JSON-RPC 测试 (initialize + tools/list)：
{
  printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}'
  printf '%s\n' '{"jsonrpc":"2.0","method":"notifications/initialized"}'
  printf '%s\n' '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
} | DEEPSEEK_API_KEY=sk-... npx -y @deepseek-harness/mcp 2>&1 | grep -o '"name":"[^"]*"'
```

期望：列出 4 个工具名。

npm URL 立刻可用：
- https://www.npmjs.com/package/@deepseek-harness/mcp

---

## 3 · 三种 install 路径全验证（README 第 1 块）

发布完后，跑这三条 README 第一段承诺的命令，确认对外宣传不假：

```bash
# (a) Python lib + CLI
pip install -U deepseek-harness deepseek-harness-cli && dsh doctor

# (b) MCP server
DEEPSEEK_API_KEY=sk-... npx -y @deepseek-harness/mcp 2>&1 | head -3

# (c) 单文件 snippet
curl -sL https://raw.githubusercontent.com/HenryZ838978/deepseek-harness/main/packages/skill/scripts/safe_init.py -o /tmp/safe_init.py
python /tmp/safe_init.py    # 期望: content: PONG | usage: {...}
```

---

## 4 · Roll-forward 升级 (0.2.0 → 0.2.1 …)

```bash
# 改完代码后：
NEW=0.3.0

# update version in 3 places:
sed -i "s/version = \"0.2.0\"/version = \"$NEW\"/" packages/core/pyproject.toml packages/cli/pyproject.toml
sed -i "s/__version__ = \"0.2.0\"/__version__ = \"$NEW\"/" packages/core/deepseek_harness/__init__.py
sed -i "s/__version__ = \"0.2.0\"/__version__ = \"$NEW\"/" packages/cli/deepseek_harness_cli/__init__.py
sed -i "s/\"version\": \"0.2.0\"/\"version\": \"$NEW\"/" packages/mcp/package.json
# also bump the trust_ledger:
sed -i "s/version: 0.2.0/version: $NEW/" docs/trust_ledger.yaml

# rebuild + re-upload:
( cd packages/core && rm -rf dist && python -m build )
( cd packages/cli  && rm -rf dist && python -m build )
python -m twine upload packages/core/dist/* packages/cli/dist/*

cd packages/mcp && npm run build && npm publish

# tag the release:
git tag -a v$NEW -m "release v$NEW"
git push origin v$NEW
```

**Semver 规则（提醒）**：
- patch (0.2.X) — 修 bug、文档、不改 API
- minor (0.X.0) — 新功能但向后兼容
- major (X.0.0) — 破坏性 API 变更（你 rename `DeepSeekClient` → `DeepSeekHarness` 那种）。当前 0.2.0 已经透明保留了别名，所以 0.X 任意 minor 都安全；真要切到 1.0.0 时再考虑去掉 transitional alias。

---

## 5 · 常见小坑

| 症状 | 可能原因 | 办法 |
|---|---|---|
| `twine upload` 报 "File already exists" | 同版本号 PyPI 不允许覆盖 | bump version → re-build → re-upload |
| `npm publish` 报 `403 You must sign up for private packages` | scoped 包默认 private，要加 `--access public` | `npm publish --access public` |
| `npm publish` 报 `402 Payment Required` | 同上，scoped private 才付费 | `--access public` |
| TestPyPI 装不上依赖 (e.g. `openai`) | TestPyPI 没有完整镜像，要 fallback 到 prod PyPI | `--extra-index-url https://pypi.org/simple/` |
| `pip install deepseek-harness` 装上但 `dsh` 不存在 | 只装了 lib 没装 cli | `pip install deepseek-harness-cli` |
| MCP 包 npx 卡住 | npx 第一次下载 deps 慢 | 第二次会从本地 cache 跑，瞬时 |
| `tsc` 编译失败 | node_modules 没装 | `cd packages/mcp && npm install` |

---

## 6 · 发完之后

1. README 顶部的 badge 会自动从 PyPI / npm 抓 latest version，第一次发布完 ~5 分钟显示出来
2. 把 https://pypi.org/project/deepseek-harness/ 和 https://www.npmjs.com/package/@deepseek-harness/mcp 加到 GitHub repo 的 About 链接
3. （可选）发到 https://hn.algolia.com 之类的看反馈
4. （可选）写 release notes：`gh release create v0.2.0 --notes-from-tag`
5. （可选）开 issue tracker、加 CONTRIBUTING.md

---

## 7 · 完整一次性命令（如果你已经全装好了）

```bash
cd /cache/zhangjing/deepseek-harness

# Python:
( cd packages/core && rm -rf dist && python -m build )
( cd packages/cli  && rm -rf dist && python -m build )
python -m twine upload packages/core/dist/* packages/cli/dist/*

# npm:
( cd packages/mcp && npm install && npm run build && npm publish --access public )

# verify:
pip install -U deepseek-harness deepseek-harness-cli && dsh version && dsh doctor
DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY npx -y @deepseek-harness/mcp 2>&1 | head -1
```

完事。
