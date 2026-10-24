# 未开张 Before Open：本地前端

用户已明确确认“先开发 React + TypeScript 本地前端，后续对接秒哒”。当前是可迁移的本地交互实现，不代表秒哒集成或参赛发布已经通过。

## 启动、构建与验证

需要 Node.js 24、npm、已准备的 Python 后端和 PostgreSQL。先按仓库根 README 安装后端、启动数据库、执行迁移。

终端一：

```bash
cd /workspace/before-open/backend
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

终端二：

```bash
cd /workspace/before-open/frontend
npm ci --cache /tmp/before-open-npm-cache --no-audit --no-fund
npm run generate
npm run check
npm test
npm run build
npm run dev
```

使用现有检出目录，不创建 Git worktree。依赖版本与制品完整性信息由 package-lock.json 固定；不需要更换全局 Node/npm，也不跳过 TLS 或强制忽略依赖冲突。

默认 Vite 只监听回环地址、使用 5173 端口。同源 `/api` 代理到 8001；需要更改后端目标时在启动命令的进程环境设置 `BEFORE_OPEN_API_TARGET`，它是开发代理配置，不是前端 API 密钥。没有对仓库根目录开放静态访问，演示资源通过生成脚本复制，不读取 .local 凭据。

生产构建输出 dist/；`npm run preview` 可在本地检查构建。真实托管需配置 SPA 路由回退和同源 `/api` 转发，不能把本地 preview 当作公网发布。没有建立用户可分享的回环地址预览链接。

## 页面和模块

| 页面 | 当前能力 |
|---|---|
| `/` | 保存用户原句；三条明确标注的演示入口；不冒充自然语言解析 |
| `/projects` | 当前匿名身份的项目列表、分页、错误恢复 |
| `/projects/:id/setup` | 三类型共用表单、来源标签、未知值、演示条件、用户确认 |
| `/projects/:id/play` | 调参数、服务端只读预览、计算依据、明确保存分支和结果 |
| `/projects/:id/compare` | 两版字段、假设及结果比较；不同需求不作同条件优劣结论 |
| `/projects/:id/experiment` | 手动任务、实际观察输入、样本与局限、读回自报记录 |

- `src/generated/api.d.ts` 由后端 OpenAPI 生成，业务 DTO 不手写第二套。
- `src/generated/fixtures.json` 来自仓库 fixtures/ 三份原始演示；前端不另造成本或需求。
- `src/lib/api.ts` 处理 HttpOnly Cookie 会话、内存 CSRF、显式幂等键、稳定错误和取消信号；不在 localStorage/sessionStorage 保存令牌。
- `src/lib/model.ts` 共用字段描述、来源标签及草稿编辑逻辑，不实现经营结算公式。
- `src/lib/money.ts` 用整数/BigInt 在元文本和分之间精确转换，不对多位小数静默舍入。
- `src/ui.tsx` 包含动态字段、预览、结果、错误和空状态；过期预览响应会被取消且不能覆盖当前结果。
- `src/App.tsx` 组织页面和用户动作；版本发布只发生在用户点击确认/保存后。

演示入口会保留用户原句，但经营数字来自显式演示条件，**不会假装从原句抽取了售价或预算**。自定义想法默认未知字段，用户手填或明确加载演示后继续。当前 AI 整理想法尚未接入，所以首页暂用手动准备说明；不会伪造 AI 进度或工具轨迹。

## 草稿预览与版本

调参数使用 `POST /api/v1/projects/{id}/preview`，沿用所有权、CSRF、来源与严格数值校验，不写入版本/模拟/幂等表，也不附带虚假的 scene_version_id。300ms 防抖与 AbortController 控制交互请求；新输入会隐藏过期结果，缺少必需条件时显示待填内容。

明确保存后才调用 branches/simulate。相同用户意图在当前页面重试沿用幂等键；观察提交时间也冻结到该次意图，防止响应丢失后重试变成“同键不同内容”。如果会话过期则显示错误，不静默切换匿名身份隐藏原项目。

## 真实浏览器验证

后端开发依赖已经锁定 Playwright 1.62.0；本环境使用已安装的 `/usr/bin/chromium`（实际版本 154.0.8037.57），不依赖被网络策略拒绝的浏览器下载。

在仓库根目录、前端 build 之后：

```bash
backend/.venv/bin/python scripts/browser_checks.py --production
```

不带 --production 时检查 Vite 开发模式。脚本自动建独立 PostgreSQL test_browser_* schema，启动自己的 API/UI，使用桌面和手机 Chromium 验证；最后停止自己的进程组并删除自己的测试 schema，不动开发项目。测试观察仅在隔离库中生成，不冒充真实调查。

本轮生产构建的 9 组浏览器场景通过；35 项前端测试、157 项后端测试通过。截图与机器可读报告写入 `.local/browser-checks/`，为当前执行生成，不代表真实用户测试。

## 秒哒迁移边界

见 [MIAODA_HANDOFF.md](../docs/MIAODA_HANDOFF.md)。官方文档当前仍被代理 403 拒绝；用户没有提供可用秒哒项目或导出代码。因此秒哒插件、发布、跨站 Cookie 和赛事规则仍待实际核实，没有用本地 React 通过来宣称平台联调通过。
