# 阶段 1 开发报告

## 已完成

完成阶段 1：规则引擎与数据契约。不接 LLM、不引入数据库、不增加前端或业务 HTTP 接口。

- **统一 SceneSpec**：Pydantic v2 按 business_type 判别三类场景；模型版本与业务类型绑定。金额使用严格整数分，数量/分钟有上限，非法类型、负数、超范围和跨业务字段拒绝。
- **来源与未知值**：六种来源、外部证据/观察引用/派生依赖校验；未知值保持 null，unknowns 根据实际字段重算。区分草稿有效和可计算，成本或需求未知不补 0；预算未知允许算利润但不计算预算缺口。
- **确定性引擎**：易损耗零售、库存可保留零售、预约服务，遵循 V4.0 的三种口径。保留库存的现金变化与期间结果分开，超出库存或产能的需求不产生收入。
- **快照与重算**：保存模型版本、原始想法、完整输入来源、需求标签、结果、结果依赖路径及 UTC 时间；深层冻结、JSON 往返和重放校验。输入和结果中的数字不会由 LLM 计算。
- **统一入口与演示**：validate_scene、simulate、run_demand_scenarios、replay_snapshot；三份 JSON 通过同一调用链直接计算，并提供 CLI。所有场景数字均标记 demo_assumption，预算未提供则保留 unknown。

## 本轮变更

新增：

```text
backend/app/schemas/{__init__,provenance,scene,simulation}.py
backend/app/simulation/{__init__,__main__,common,retail,service,runner}.py
backend/tests/conftest.py
backend/tests/unit/{test_provenance,test_scene,test_retail,test_service,test_runner}.py
fixtures/{retail_perishable,retail_durable,appointment_service}.json
docs/SCENE_SCHEMA.md
docs/scene.schema.json
docs/PHASE1_REPORT.md
```

更新：README 的当前状态、三条演示命令和 Python 示例；PHASE1_PLAN 标记已实现；原健康测试仅格式整理，无逻辑变化。依赖清单、锁文件、原服务逻辑、AGENTS.md 与 V4.0 基线未改。没有删除文件、读取密钥、创建 Git 提交、推送或公网部署；原阶段 0 文件与本轮新增文件目前都尚未提交。

## 实际测试

工作目录 `/workspace/before-open/backend`：

| 命令 | 结果 |
|---|---|
| `.venv/bin/python -m pytest -q` | **99 passed，1 warning**；含原有 2 项健康服务测试 |
| `.venv/bin/ruff check .` | All checks passed |
| `.venv/bin/mypy` | Success，19 个源文件无类型问题 |
| README 的三条 `python -m app.simulation ...` 命令 | 三类场景均成功输出 JSON 快照，共 5 次情景结果；随后逐条 replay_snapshot 校验成功 |

测试覆盖四个 V4.0 算例、零需求/库存/固定费/单价、预算临界点与未知预算、现金和库存成本的恒等关系、产能不足与零可用分钟、取消超预约拒绝、最大数值与一分钱、bool/float/字符串拒绝、未知字段与来源元数据、跨业务与版本错误、JSON 往返、派生路径对应实际输入、选中情景与不完整批次、深层不可变、修改价格不改变需求、篡改快照、含时区时间、CLI 成功及缺失输入的错误返回，以及导出 Schema 与代码一致性。

实际算例：

| 算例 | 验证结果（金额单位：分） |
|---|---|
| 冰粉，需求 12 | sold=12，unsold=18，cash_out=22500，result=-11700 |
| 冰粉，需求 45 | sold=30，unsold=0，result=4500 |
| 饰品，需求 8 | cash_change=-5000，simplified_period_profit=2200，unsold=12，inventory_cost=7200 |
| 摄影，预约 6、取消 1 | capacity=4，completed=4，simplified_result=32000 |

开发中 Ruff 检出泛型语法和格式问题，mypy 检出 TypeAdapter 的联合构造器标注限制及 CLI 元组推断问题，均已处理后重新验证；没有未解释的失败。TypeAdapter 的局部类型忽略仅针对其构造器签名限制，三类实际 JSON 校验和 Schema 导出有运行测试支持。

遗留警告仍为阶段 0 的 Starlette TestClient/httpx 弃用提示；没有隐藏警告或新增另一套 HTTP 测试依赖。

## 已知问题与边界

- 来源校验仅保证结构正确。真实观察 ID 的存在、归属和来源写入权限必须在阶段 2/4 落实；本阶段不宣称来源被现实核验。
- SceneVersion ID 由调用者传入；CLI 用 demo-*，不代表真实版本已保存。快照当前是可序列化值对象，不是数据库持久化或事务保证。
- 读取不可信快照要用 replay_snapshot 重算；类型校验本身不证明结果真实。未来增加公式版本须保留旧版计算逻辑。
- 没有测试数据库并发、权限、API 幂等、Agent 行为或前端闭环；它们尚未实现。秒哒和赛事规则仍是阶段 0 记录的待核实项。

## 可复用环境配置

沿用此前 cloud-environment-onboarding:setup 技能的配置约定，已成功更新云草稿的 start_skill，记录当前阶段、三类演示与验证命令；install_script 不变，原脚本会安装锁定依赖并运行当前完整检查。网络、变量、密钥和仓库列表未变。工具返回 saved、requires_publish=true；仍需用户在环境设置审阅、保存并发布，未声称已发布或新任务恢复成功。

## 下一阶段

停止在阶段 1。下一阶段只做阶段 2：业务 API 与持久化。

1. 检查可用 PostgreSQL 配置，建立 SQLAlchemy 2.x 模型和 Alembic 迁移，验证生产数据库语义。
2. 创建项目、确认不可变场景版本、运行并保存模拟、建立独立分支及版本对比；数据库保存输入快照和模型版本。
3. 实现匿名会话所有权、统一 request_id/错误码、来源写入边界、幂等键及事务，避免重复分支或跨用户访问。
4. 为后续 Agent 执行摘要、实验任务与用户观察准备数据契约和存储，不提前接模型；完成持久化、权限、迁移和并发集成测试。
