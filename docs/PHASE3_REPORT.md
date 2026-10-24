# 阶段 3：动态 UI 开发报告

## 路线与已完成内容

用户本轮明确确认：“先开发 React + TypeScript 本地前端，后续对接秒哒”。本轮据此实现本地前端，不将其当作秒哒平台集成或赛事发布已经通过。V4.0 和 AGENTS.md 原文未改。

已完成六个页面：首页、手动场景准备、创意沙盒、方案比较、现实挑战、我的想法。三类业务使用同一套动态表单、统一 SceneSpec 与服务器引擎，未分别硬编码三套业务页面。

- **界面**：奶油白/暖橙/鼠尾草绿、轻量场景示意、桌面与手机响应式布局；来源文字标签、键盘跳转、表单标签和可见焦点。插画仅作示意，不充当业务证据。
- **准备**：保存原始想法，手动选择经营方式、填写地点/期间和条件；自定义想法的数值默认未知。演示入口明确由用户选择，数字保留演示来源，不冒充从原句解析得到。
- **沙盒**：严格金额文本转整数分，共用字段组件，300ms 防抖后向后端 preview 试算；参数无效或不完整时隐藏旧结果并显示待填项；取消旧请求，过期响应不覆盖新条件。
- **保存**：仅点击确认/保存才创建场景版本、分支和模拟记录。创建请求使用稳定幂等键；网络丢失响应后重试不重复新增方案。只读调参不产生版本堆积。
- **比较**：展示两版结果、字段差异、未改变的条件、需求和期间是否一致。不同需求不会被宣传为同条件优劣。
- **现实挑战**：用户手动编写任务、录入实际观察、样本量和局限；保留自报来源，不自动改写原方案或宣称外部核验。测试中的模拟观察只写入隔离数据库并清理。
- **异常**：加载、空状态、404、未知条件、断网、重试、会话错误与渲染边界；不伪造 AI 进度。匿名身份过期不会自动换成新身份隐藏旧项目。

当前没有自然语言解析、LangGraph 或 Agent 工具选择。首页使用手动准备说明，避免把阶段 4 的能力提前写成已实现。

## 本轮变更

新增前端：

```text
frontend/package.json、package-lock.json、tsconfig.json、vite.config.ts、index.html
frontend/src/{main.tsx,App.tsx,ui.tsx,style.css}
frontend/src/lib/{api.ts,types.ts,model.ts,money.ts}
frontend/src/generated/{api.d.ts,fixtures.json}
frontend/scripts/generate-fixtures.mjs
frontend/tests/{api,model,money}.test.ts
frontend/README.md
```

新增后端/验证：`PreviewRequest`、`CalculationPreview`、纯 preview 入口及 `POST /projects/{id}/preview`；`backend/tests/integration/test_preview_api.py`；`scripts/browser_checks.py`。simulate 复用同一计算链，仅在保存路径附加业务版本 ID；零售/服务公式未改，也没有数据库迁移变更。

更新：后端版本 0.3.0、依赖与锁文件（开发测试使用 Playwright 1.62.0）、生成 OpenAPI、根 README、API/Schema/决策说明、忽略目录。新增 `docs/MIAODA_HANDOFF.md` 与本报告。没有删除用户文件、读取输出密钥、创建 Git 提交、推送或公网部署。

## 实际验证结果

| 验证 | 结果 |
|---|---|
| `npm ci --cache /tmp/before-open-npm-cache --no-audit --no-fund` | 固定锁文件安装成功 |
| `npm run generate` | TypeScript DTO 来自 OpenAPI，演示资源来自仓库 fixtures |
| `npm run check` | 严格类型检查通过，包含未使用符号检查 |
| `npm test` | **35 项通过，3 个测试文件** |
| `npm run build` | 生产构建成功；JS 约 261.28 kB / gzip 81.59 kB，CSS 约 12.25 kB |
| `backend/.venv/bin/python scripts/browser_checks.py --production` | **9 组真实浏览器场景通过**，使用生产构建与真实 PostgreSQL |
| 后端 `python -m pytest -q` | **157 项通过，1 项既有警告** |
| `ruff check . ../scripts`、`mypy` | 通过；mypy 检查 38 个源文件 |
| `alembic check` | 无模型/迁移漂移 |
| 当前运行实例 | 前端 HTML、同源 /api 代理、健康及 PostgreSQL ready 成功 |

新增 10 项参数化后端预览检查在 SQLite 与 PostgreSQL 运行：三类算例、无版本 ID、无永久写入、所有权/CSRF/来源、未知条件不计算。既有持久化、版本、并发和四个 V4.0 算例继续通过。

前端单元测试验证整数分精确转换、边界拒绝、未知值、原始想法保留、演示来源、调价格不改需求、服务取消约束、会话共享、Cookie/CSRF、显式幂等键、稳定错误和取消信号。

真实浏览器场景：

1. 桌面首页、表单标签、键盘跳转、无横向溢出。
2. 冰粉：非法输入不显示旧结果，调整备货获得服务器结果，确认分支后刷新仍可读。
3. 比较原方案和新方案，原版结果保留。
4. 手动任务、观察、样本与局限保存，刷新读回自报来源。
5. 项目列表断网后可重试，不白屏。
6. 手机饰品/摄影：不同字段、现金/期间口径、分钟产能、调参及布局。
7. 预览断网时清除旧数字，并可重试。
8. 模拟保存请求已提交但响应丢失，重试只创建一个新分支。
9. 故意延迟旧预览，确认不会覆盖新参数结果；无未捕获页面异常。

浏览器测试使用独立 test_browser_* PostgreSQL schema，自动启动/清理自己的 API/UI 进程组，结束后删除自己的 schema。没有清空开发库，也没有将虚构观察留在开发项目。

## 截图与运行

实际生产构建截图及机器报告位于 `.local/browser-checks/`：home-desktop.png、sandbox-desktop.png、comparison-desktop.png、durable-mobile.png、service-mobile.png、report.json。已查看桌面和手机截图并修正手机跳转链接显示。它们是当前执行的界面记录，不是用户体验研究结论。

启动、端口、构建、验证和生成命令见 [frontend/README.md](../frontend/README.md)。当前本地开发前端与最新 0.3.0 API 已启动。没有创建用户可分享的回环地址预览链接；本地运行不等于发布。

## 排障与已知限制

- npm 默认缓存路径不可写，改用 `/tmp/before-open-npm-cache`。openapi-typescript 要求 TypeScript 5.x，使用兼容的 5.9.3，未用 force/legacy-peer-deps 绕过冲突。
- Playwright 默认浏览器不存在，下载被 CDN 网络策略 403 拒绝。使用环境已经安装的系统 Chromium 154.0.8037.57 实际完成测试，未降低 TLS/制品校验或假称下载成功。
- 保留既有 Starlette TestClient/httpx 弃用警告；没有忽略失败或跳过必需测试。
- 秒哒官方文档仍被代理 403 拒绝，未提供项目/导出资源；平台插件、跨站 Cookie、发布权限和赛事规则尚未实测。本地同源代理的通过不替代秒哒联调。
- 生产同源转发、独立持久数据库与备份、多人/多实例部署没有执行。Docker 命名卷不保证随云文件快照恢复。
- 当前没有账号恢复功能；匿名凭据过期/浏览器数据丢失时不会自动恢复项目。没有宣称完成真实新手用户测试或完整无障碍审计。

## 可复用云配置

沿用本会话的 cloud-environment-onboarding:setup 技能，已成功更新 install_script 与 start_skill，包含锁定安装、前后端检查、生产构建、隔离浏览器验证、服务启动和 readiness。工具返回 saved、requires_publish=true；仅保存草稿，尚未发布或验证新任务恢复。网络、变量、密钥及仓库成员未修改。

## 下一阶段

停止在阶段 3。下一阶段仅做阶段 4：单个 ScenarioAgent 的意图解析、业务路由、主动澄清、结构化草稿、白名单工具选择、真实执行轨迹、用户确认中断和故障降级。经营结果继续由现有引擎计算。接入模型前需核实可用服务和凭据，不擅自调用付费接口或把演示数据当作现实核验。
