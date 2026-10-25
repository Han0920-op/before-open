# HTTP API V1：阶段 2

接口前缀 `/api/v1`。结构以 [openapi.json](openapi.json) 为准，由 FastAPI/Pydantic 自动生成；前端不得另定义不一致的 SceneSpec 或金额类型。本文解释请求顺序、权限与来源边界。

## 匿名会话与写入顺序

1. `GET /session` 建立匿名会话，返回 csrf_token、expires_at，并写入随机不可猜测的 HttpOnly/SameSite=Lax Cookie。再次调用沿用当前有效会话；无效/过期 Cookie 返回 401，不默默换成另一个身份。
2. 后续业务请求携带 Cookie；所有 POST 另发 `X-CSRF-Token`。Cookie 原文和 CSRF 原文不写入数据库，数据库分别保存摘要。
3. 创建类请求还需 `Idempotency-Key`（1～128 位字母数字或 `._:-`）。同会话、同键、同路径和语义输入返回相同 data；不同输入/路径复用键返回 409。每次请求仍有新的 request_id。
4. 先创建 project，再手动提交 SceneSpec 并明确 `confirmed=true`；整数 1、false 或缺少确认均拒绝。SceneSpec 的 original_idea 必须逐字匹配项目的原始想法。
5. 通过持久版本 ID 模拟或创建子版本；不允许 PATCH/DELETE 覆盖旧版本。未知成本可保存为版本，但缺少计算参数时不能模拟。

Cookie 是匿名访问凭据，应像口令一样保护，不能用于公开分享。所有项目、版本、模拟、实验与 Agent 记录读取/写入都检查会话所有权；外部用户与不存在的资源统一返回 404，减少存在性泄漏。

## 响应与错误

业务成功：`{"request_id":"...","data":...}`。错误：`{"request_id":"...","error":{"code":"...","message":"..."}}`。每次响应有 X-Request-ID、Cache-Control=no-store；错误不回显请求正文、SQL、绑定值或凭据。

健康接口保留阶段 0 的 `{"status":"ok","request_id":"..."}`；OpenAPI/Swagger 和 CORS 协议响应按框架格式返回，仍有 X-Request-ID。健康只证明进程可用；ready 会实际查询迁移版本。业务数据库未配置时健康仍可用，业务返回 503。

| 情况 | 状态 / code |
|---|---|
| 无匿名会话 / 过期 | 401 SESSION_REQUIRED / SESSION_EXPIRED |
| 缺少或不匹配 CSRF | 403 CSRF_INVALID |
| 非白名单来源写入 | 403 ORIGIN_FORBIDDEN |
| 非法字段、类型、确认或头 | 422 INVALID_INPUT |
| 原始想法被改写 | 422 ORIGINAL_IDEA_IMMUTABLE |
| 手动声明核验或派生来源 | 422 SOURCE_FORBIDDEN |
| 观察不存在/非本项目/值或单位不符 | 422 OBSERVATION_MISMATCH |
| 不完整场景 / 不存在情景标签 | 422 SIMULATION_NOT_READY / INVALID_SCENE |
| 版本不属同项目 / 不同业务模型比较 | 422 PROJECT_MISMATCH / INCOMPATIBLE_MODELS |
| 同键用于其他内容 | 409 IDEMPOTENCY_CONFLICT |
| 请求正文超过 256 KiB / 读取超过 10 秒 | 413 BODY_TOO_LARGE / 408 REQUEST_TIMEOUT |
| 超过单进程每 IP 每分钟 120 请求 | 429 RATE_LIMITED |
| 数据库不可用或事务失败 | 503 DATABASE_UNAVAILABLE |

## 当前可用接口

| 方法 / 路径 | 作用 | 幂等键 |
|---|---|---|
| GET /health、/ready | 进程/数据库迁移健康 | 否 |
| GET /session | 建立/恢复匿名会话，获取 CSRF | 否 |
| POST /projects | 创建原始想法 | 是 |
| GET /projects | 当前会话列表，limit 1～100、offset ≥0 | 否 |
| GET /projects/{id} | 项目、版本与最新版本 ID | 否 |
| POST /projects/{id}/scene-confirm | 用户确认并冻结手动场景 | 是 |
| POST /projects/{id}/preview | 调整中的草稿只读试算，不创建版本或模拟记录 | 否，但需要 CSRF |
| GET /scene-versions/{id} | 读取版本 | 否 |
| POST /scene-versions/{id}/branches | 提交完整修改后的场景，追加子版本 | 是 |
| POST /scene-versions/{id}/simulate | 选择 scenario_label，计算并保存结果 | 是 |
| GET /scene-versions/{id}/simulations | 版本模拟记录 | 否 |
| GET /simulation-runs/{id} | 读取并重算校验保存的结果 | 否 |
| POST /projects/{id}/compare | 只读比较两个已有版本与选定情景 | 否，但需要 CSRF |
| POST /projects/{id}/experiments | 保存用户手动编写的现实挑战 | 是 |
| GET /experiments/{id} | 读取任务 | 否 |
| POST /experiments/{id}/observations | 保存用户明确录入的观察 | 是 |
| GET /projects/{id}/agent-runs/{run_id} | 只读已存在的执行摘要和工具记录 | 否 |
| GET /projects/{id}/summary | 结构化复盘数据，不调用 LLM | 否 |

POST 创建成功及同键重放均返回 201。比较不保存新版本或模拟记录；结果含字段差异、未改变字段、经营结果差值（右减左）、需求假设是否相同、期间是否相同、计算字段是否相同。same_calculation_inputs 比较完整 fields 来源包装与选中需求，不包含期间；same_period 单独报告。改变价格/备货会使输入不同，结果不附带“哪个一定更好”的结论。

## 数据来源与观察

- 手动确认允许 user_input、demo_assumption、unknown；不开放客户端 mint verified_external 或 derived。即使输入有合法 URL 或派生路径也会拒绝。
- user_observation 必须引用本项目已保存的观察，且数值和单位与记录一致。不能跨项目使用观察，即使两个项目属于同一会话。
- 观察要求记录时间、sample_size、notes、limitations 和 observed_values；provenance 固定为 user_observation，客户端不可传入其他来源。
- observed_values 是字段名到 `{value,unit}` 的映射，unit 为 cents/qty/minutes。当前支持数值经营观察；地点等文字信息保存在备注，不通过这个入口变成“地点已核验”。
- 任务自动附加“征得参与者同意、不记录姓名联系方式、样本不代表市场”的提醒。系统不替用户开展调查，也不自动把观察应用到原方案。

## 数据库与事务

SQLAlchemy 2.x + Alembic。初始迁移含业务基线的八张表，加匿名会话与幂等记录两张表。项目原句、场景版本、模拟和观察受数据库触发器保护；父版本及实验任务的项目归属由复合外键约束。版本/模拟/观察的 ORM 更新、删除也会拒绝。

幂等键唯一约束与业务写入在同一事务；冲突插入使用保存点，失败事务回滚写入及请求键，响应发送前提交。PostgreSQL 实测四个同键并发分支请求只产生一个子版本。SQLite 明确使用 BEGIN IMMEDIATE 串行开发访问，避免旧事务模式提前提交保存点；它不替代 PostgreSQL 的并发验证。

PostgreSQL 连接超时 5 秒、锁等待上限 5 秒、语句上限 10 秒。读取请求正文有独立 10 秒时限；不是取消已提交业务写入的总请求 deadline。限流是进程内的基础防护；多实例公网部署仍需网关层限流、HTTPS、备份和部署权限检查。

## 阶段边界

阶段 3 新增 preview：请求为 `{scene, scenario_label}`，返回 CalculationPreview，包含完整输入、模型版本、结果、来源依赖和时间，但不附加 scene_version_id，不宣称草稿已经冻结。所有权、来源、CSRF 和数值规则与保存/模拟相同；版本、模拟和幂等表均不写入。只有用户明确保存时才调用原 branches/simulate。

阶段 4 已接入 LangChain/LangGraph 的服务接口、断点存储及工具轨迹，新增路由和模型隐私约定见 [AGENT_GUIDE.md](AGENT_GUIDE.md)。不存在记录仍返回 404，没有对客户端开放伪造工具记录的接口。真实服务商调用尚待用户提供密钥与网络条件验证，不把测试模型当作真实联调通过。

秒哒跨域接入、跨站 Cookie、赛事规则与用户体验均尚未验证；当前 CORS 是显式白名单、Cookie SameSite=Lax，不宣称适用于任意跨站 H5。

## 重新生成 OpenAPI

在 backend 目录：

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
from app.core.config import Settings
from app.main import create_app

Path('../docs/openapi.json').write_text(
    json.dumps(create_app(Settings()).openapi(), ensure_ascii=False, indent=2) + '\n'
)
PY
```

自动测试检查该文件与当前路由模型一致。完整 Python 调用、三类演示和启动步骤见 README。
