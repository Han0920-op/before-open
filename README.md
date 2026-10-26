# 未开张 Before Open

当前已实现阶段 4 核心代码：模型接入页、单个 ScenarioAgent、自然语言事实抽取、澄清、人工确认、白名单工具、风险卡和可恢复工作流。前端仍为用户确认的 React + TypeScript 本地版。真实服务商联调待用户接入密钥验证；测试模型不代表真实模型准确率。秒哒发布尚未验证。

需求基线：[V4.0](未开张_BeforeOpen_开发智能体执行方案_V4.0.md)；工作约定：[AGENTS.md](AGENTS.md)。上传的 Markdown 原样归档，DOCX 不作为第二套基线。

后续开发与验收同时参考[“秒哒校园”作品评分标准及开发检查项](docs/COMPETITION_RUBRIC.md)：美观度、可用性、创新性各 0～5 分。该参考来自用户提供的评分表截图，补充质量目标，不替代 V4.0 或扩张产品范围。

**第一次在自己的电脑运行：请看 [快速启动教程](docs/QUICKSTART.md)**。包含克隆代码、准备工具、启动数据库及前后端的完整步骤，不依赖云环境目录。

**Windows 一键启动：** 安装 uv、Node.js 24 和 Docker Desktop，打开 Docker 后双击根目录的 [`start.bat`](start.bat)。脚本自动准备依赖、启动数据库、迁移并启动前后端，就绪后打开浏览器；在同一窗口按 Ctrl+C 停止前后端。首次运行需联网，详细前置条件见快速启动教程。

- [阶段 0 检查结果与技术决策](docs/DECISIONS.md)
- [阶段 1 文件、数据模型和测试计划](docs/PHASE1_PLAN.md)
- [阶段 1 实施结果与测试记录](docs/PHASE1_REPORT.md)
- [场景 Schema 与计算契约](docs/SCENE_SCHEMA.md)
- [阶段 2 实施与验证报告](docs/PHASE2_REPORT.md)
- [业务 API 契约](docs/API_CONTRACT.md) / [生成的 OpenAPI](docs/openapi.json)
- [阶段 3 报告](docs/PHASE3_REPORT.md) / [前端运行说明](frontend/README.md)
- [后续秒哒对接说明](docs/MIAODA_HANDOFF.md)
- [阶段 4 开发报告](docs/PHASE4_REPORT.md) / [模型接入与 Agent 使用](docs/AGENT_GUIDE.md)

## 安装与验证

需要 Python 3.12 与 uv（本环境 uv 0.12.23）。API 及集成测试还需要 PostgreSQL；本地使用 Docker 启动固定摘要的 PostgreSQL 17 镜像。依赖确切版本及制品校验信息保存在 `backend/uv.lock`，日常安装不更新锁文件。

```bash
cd /workspace/before-open
python3 scripts/dev_db.py
cd backend
export UV_CACHE_DIR=/tmp/before-open-uv-cache
export UV_LINK_MODE=copy
uv sync --locked --no-install-project
.venv/bin/alembic upgrade head
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/mypy
```

虚拟环境保存在 `backend/.venv`，不提交。开发数据库脚本仅绑定回环地址、随机生成本地口令、保存到被忽略的 `.local/`（权限 700，凭据文件 600），重复执行会启动本脚本拥有的现有容器，不覆盖旧配置。不会输出口令。数据库已启动后，后端的安装、迁移与验证命令均可重复执行。

也可通过进程环境的 `DATABASE_URL` 使用已有 PostgreSQL，不运行本地 Docker 脚本；不要将完整连接串写入聊天、日志或提交。集成测试使用独立临时 schema，不删除开发库数据；仍需要 PostgreSQL，不能只用 SQLite 的通过结果替代。应用不自动读取 `.env`。默认不调用模型；用户接入并授权后才向选定模型服务发送本项目必要数据。LangSmith 追踪关闭，不接外部商业数据库。

注意：本地 PostgreSQL 数据位于 Docker 命名卷，API/进程重启不会丢失，但不保证随云环境文件快照恢复。生产数据应使用独立持久 PostgreSQL 并备份；发布环境快照不等于发布/备份数据库。若容器丢失而本地凭据仍存在，脚本会停止以保护旧数据，不盲目新建空库。

## 启动

本地前端和浏览器测试命令见 [frontend/README.md](frontend/README.md)。前端开发代理默认使用 8001 端口 API；如同时启动前端，将以下命令的 `--port 8000` 改为 `--port 8001`。

```bash
cd /workspace/before-open/backend
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另一个终端验证：

```bash
curl --fail --silent http://127.0.0.1:8000/api/v1/health
```

预期 HTTP 200，JSON 的 `status` 为 `ok`、`request_id` 为 UUID。仅证明进程响应，不代表业务、数据库或 AI 已就绪。OpenAPI 由 FastAPI 在 `/openapi.json` 生成，不手写第二套接口定义。

`GET /api/v1/ready` 进一步检查数据库及迁移版本。匿名业务入口是 `GET /api/v1/session`；浏览器保留返回的 HttpOnly Cookie，并为写请求发送响应中的 `csrf_token`（`X-CSRF-Token`）。创建项目、确认版本、模拟、分支及观察等写操作还要发送 `Idempotency-Key`。详细交互见 API_CONTRACT。

外部数据库默认 Cookie Secure=true；仅本地脚本配置默认 false 以供回环 HTTP 开发。跨域前端需设置显式 `ALLOWED_ORIGINS`，不能用 `*`。当前没有为秒哒接入配置跨站 Cookie 策略，不能声称平台联调通过。

云任务已有独立环境，使用本目录，不创建 Git worktree。发布快照不保留进程；新任务需要重新启动服务。这里的回环地址只供内部验证，不是可分享的网页预览。

## 直接运行三种经营场景

在 `backend` 目录执行，无需启动 Web 服务、配置密钥或接入 LLM：

```bash
.venv/bin/python -m app.simulation ../fixtures/retail_perishable.json --scene-version-id demo-ice
.venv/bin/python -m app.simulation ../fixtures/retail_durable.json --scene-version-id demo-jewelry
.venv/bin/python -m app.simulation ../fixtures/appointment_service.json --scene-version-id demo-photo
```

输出是快照 JSON 数组：冰粉为显式 low/medium/high 三种需求假设，饰品与摄影各一条。可加 `--scenario-label low` 只算冰粉 low；可加 `--calculated-at 2026-10-24T12:00:00+00:00` 固定记录时间。示例 ID 不代表数据库里已存在版本。所有数据仅为 V4.0 演示假设，不是市场成本、真实销量或核验结论。

预期：冰粉 low 为 **-11700 分**、high 为 **4500 分**；饰品现金变化 **-5000 分**、简化期间结果 **2200 分**；摄影完成 **4 单**、简化结果 **32000 分**。输入没有预算时缺口保持 `null`；调整售价不会自动改变需求。

Python 使用方式：

```python
import json
from datetime import UTC, datetime
from pathlib import Path

from app.simulation.runner import replay_snapshot, simulate, validate_scene

raw = json.loads(Path("../fixtures/retail_perishable.json").read_text())
assert validate_scene(raw, "low").ready
run = simulate(
    raw,
    scene_version_id="demo-ice",
    scenario_label="low",
    calculated_at=datetime(2026, 10, 24, 12, tzinfo=UTC),
)
assert replay_snapshot(run) == run
```

场景不完整时 CLI 以退出码 2 和结构化错误结束，不补造成本或需求。CLI 保持纯本地计算，不自动保存数据库；API 的 simulate 入口会保存输入、来源、模型版本与结果。UI 调参使用只读草稿 preview，不创建永久版本；只有用户明确保存才创建分支和模拟记录。Agent 接入方式与真实模型联调要求见 AGENT_GUIDE。
