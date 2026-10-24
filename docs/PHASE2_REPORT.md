# 阶段 2：业务 API 与持久化开发报告

## 已完成

本轮仅执行阶段 2，不开发前端、不接 LLM/LangGraph，也不创建假的 Agent 执行记录。

- **PostgreSQL 持久化**：SQLAlchemy 2.x、psycopg、Alembic 初始迁移。业务基线八张表，加匿名会话和幂等记录，共十张应用表（另有 Alembic 自身版本表）。数据库实际使用 PostgreSQL 17.11。
- **项目与版本**：保存原始想法；确认后创建不可变场景；完整场景修改创建独立子版本，不覆盖父版本。原句、版本、模拟、观察有数据库触发器保护；父版本与实验任务的项目归属有复合外键约束。
- **模拟与比较**：复用阶段 1 的纯计算入口，保存模型版本、输入来源、快照和结果；读取记录时重算校验。版本比较报告改变/未改变的字段、需求假设、期间、计算输入与结果差值，不把不同假设称为同条件预测。
- **匿名权限**：随机会话凭据、HttpOnly Cookie、摘要存储、过期校验；所有资源读取/写入检查项目所有权；CSRF、显式 Origin/CORS 白名单、正文上限、正文读取超时、数据库超时与进程内限流。
- **幂等与事务**：同会话同键同输入重放同一结果；不同输入冲突返回 409；业务数据和幂等记录同事务，失败均回滚，提交发生在响应发送之前。
- **手动任务与观察**：保存用户编写的现实任务及自报观察、样本量、局限和数值单位。观察引用必须属于本项目并匹配值/单位；客户端不能宣称外部核验或派生来源。没有自动开展真实调查。
- **执行摘要存储**：AgentRun、ToolInvocation、RiskCard 已有表结构，已有 Agent 摘要只读接口；未产生实际 Agent 执行，不对客户端开放伪造工具记录的接口。
- **生成契约**：统一 request_id、稳定错误码、自动生成且有一致性测试的 OpenAPI；健康接口保持兼容，ready 额外检查数据库迁移。

## 本轮变更

新增：

```text
backend/.env.example                          # 变量名示例，不含凭据，应用不自动加载
backend/alembic.ini
backend/alembic/{env.py,script.py.mako,versions/0001_initial.py}
backend/app/core/{__init__,config,database,errors,security}.py
backend/app/models/{__init__,entities}.py
backend/app/services/{__init__,business}.py
backend/app/api/{__init__,routes}.py
backend/app/schemas/api.py
backend/tests/integration/{__init__,conftest,test_business_api,test_contract_guards}.py
scripts/dev_db.py
docs/API_CONTRACT.md
docs/openapi.json
docs/PHASE2_REPORT.md
```

修改：app/main.py 改为应用工厂并注册 API/错误处理/防护；pyproject.toml 与 uv.lock 增加数据库依赖、版本更新为 0.2.0；README 更新启动、迁移、验证与数据持久化说明；.gitignore 忽略 .local 和本地数据库文件。

未修改阶段 1 经营公式、SceneSpec 或三份演示 fixture；AGENTS.md 与 V4.0 原文未变。没有删除用户文件、重写历史、提交或推送代码、调用收费服务或部署公网。整个仓库仍无 Git 提交，阶段 0/1 的文件和本轮文件都尚未提交。

本地生成的 .local/ 保存私有开发数据库凭据，不进入 Git、报告、OpenAPI 或保存的脚本。Docker 数据保存在本脚本拥有的命名卷，容器只发布 127.0.0.1:5432；镜像固定到实际拉取验证的 PostgreSQL 17 摘要。

## 实际执行与验证

| 操作 | 结果 |
|---|---|
| `python3 scripts/dev_db.py` | 本地 PostgreSQL 启动并等待就绪；重复执行成功，未覆盖配置 |
| `uv sync --locked --no-install-project`（配置 /tmp 缓存与 copy 模式） | 安装成功，重复执行无需改动依赖 |
| `.venv/bin/alembic upgrade head` | 实际 PostgreSQL 升级至 0001；再次执行成功 |
| `.venv/bin/alembic check` | No new upgrade operations detected |
| `.venv/bin/python -m pytest -q` | **147 passed，1 warning，无跳过/禁用项** |
| `.venv/bin/ruff check . ../scripts` | All checks passed |
| `.venv/bin/mypy` | Success，37 个源文件无类型问题 |

147 项含阶段 1 及健康服务的原 99 项，加本轮 48 项 API/数据库/安全检查。数据库集成用例分别在 SQLite 临时文件、真实 PostgreSQL 独立 test_* schema 运行，不以 SQLite 通过替代 PostgreSQL。测试结束仅清理本轮测试创建的 schema/文件，不清理开发库。

已验证：三种模型的 API 计算；新应用/连接重新读取保存记录；分支不覆盖父版本；原始想法拒绝改写；字段及假设差异；跨会话所有资源访问拒绝；CSRF/Origin/CORS/Cookie；过期会话；正文大小、超时及限流；非法来源拒绝；观察归属、数值、单位与局限；数据库复合外键；直接 SQL 更新/删除不可变记录被拒绝；隔离测试库完整降级再升级；同键四个并发请求只创建一个分支；冲突键 409；业务写入后故意失败时模拟记录及幂等键同时回滚，原键随后可重试。

**真实 HTTP 验证**：启动 API，在当前 PostgreSQL 创建明确标记的演示项目、确认版本、模拟、同键重放、分支和比较；第二个匿名会话访问返回 404。再启动独立 API 子进程，使用原会话读回完全相同的模拟，并通过快照重算校验；验证后仅停止该临时子进程。未向开发库录入虚构的“真实用户观察”。

当前最新服务在内部 8001 端口运行，健康、PostgreSQL ready、OpenAPI 0.2.0、CSRF 头与 408 契约均验证成功。先前由本会话启动的旧阶段 0 服务已停止；没有终止未知进程。没有创建公网或回环地址的用户预览链接。

## 发现并修正的问题

- SQLite 默认事务模式会使独立保存点提前提交幂等记录，导致业务失败后留下键。通过故意失败测试定位，改为 SQLAlchemy 显式 BEGIN IMMEDIATE，保证外层事务回滚；并发开发访问串行。PostgreSQL 使用自己的原生并发/事务，四请求并发用例通过。
- SQLite 丢失 DateTime 时区，曾使观察复盘校验失败。写入观察前统一 UTC，读回时间显式恢复 UTC，两个数据库上的观察与复盘测试均通过。
- 配置对象 repr 隐藏数据库连接串，避免诊断输出带出口令；错误和日志不回显 SQL、绑定值或用户正文。
- 既有 Starlette TestClient/httpx 弃用警告仍有 1 项；未隐藏或禁用测试，无未解释失败。

## 可复用云配置

沿用本会话的 cloud-environment-onboarding:setup 技能约定，已成功更新 install_script 与 start_skill：数据库准备、锁定安装、迁移、检查、启动、会话与健康验证均有说明。网络、变量、密钥和仓库成员未改。

工具返回 saved、requires_publish=true，说明草稿保存成功；尚未发布，也未验证新云任务恢复。需要发布时在环境设置审阅、保存并发布。不能把文件快照当成 Docker 数据卷备份；数据持久性限制如下。

## 已知问题与限制

- PostgreSQL 命名卷可跨 API/容器进程重启保留数据，但不保证跨云环境快照恢复。真实业务应使用独立持久 PostgreSQL 和备份。若只剩本地凭据却找不到旧容器，脚本会停止保护数据，不能删除配置后用空库冒充恢复。
- 限流为单进程基础限制；公网多实例部署仍需网关、HTTPS、备份和监控。尚未进行公网部署或多实例压测。
- 用户观察为自报，不等于外部核验；当前结构化观察仅支持数值经营字段，地点等文字保存在备注。客户端不能创建 verified_external/derived 事实。
- 秒哒 API、跨站 Cookie、比赛规则尚未核实；本地 CORS 测试不证明平台联调成功。
- scene-draft/clarifications/experiment-draft 的 AI 生成入口留待阶段 4；没有 LLM、LangGraph 或真实工具编排。当前 summary 是结构化事实读取。

## 下一阶段

停止在阶段 2。下一阶段仅执行阶段 3：轻松的动态 UI。

先核实秒哒可用项目、导出资源、外部 API 和权限/发布条件；复用本轮 OpenAPI、会话和 fixtures，构建首页、手动场景准备、三类型动态沙盒、方案比较与现实挑战骨架。优先完成手机/桌面可操作链路和异常状态，不做大型装饰功能，也不提前接 Agent。若秒哒权限/资源仍不可用，先报告明确缺口，不擅自用另一套前端替代参赛要求。
