# 阶段 1：经营引擎与数据契约实施计划

状态：已按本计划实现，实际文件与验证结果见 [PHASE1_REPORT.md](PHASE1_REPORT.md)。下文保留阶段 0 制订的原始规格；实现细节和接口解释以 [SCENE_SCHEMA.md](SCENE_SCHEMA.md) 为准。

目标：不用 LLM、不依赖数据库即可在 Python 中校验并计算冰粉、饰品和摄影三类情景。保留预算冲突与产能不足等结果，不把不利结果当作输入错误。业务 API、持久化、UI 和 Agent 不在此阶段实现。

## 预计新增文件与职责

```text
backend/app/
  schemas/
    __init__.py
    provenance.py    # 来源枚举、字段包装、核验证据与依赖引用
    scene.py         # 三种 SceneSpec 判别联合、字段与模型版本兼容
    simulation.py    # 执行输入、结果联合、缺失字段诊断、运行快照
  simulation/
    __init__.py
    common.py        # 严格边界、金额/数量单位、模型版本注册和预算检查
    retail.py        # 易损耗/可保留零售的纯计算
    service.py       # 预约、取消、分钟产能的纯计算
    runner.py        # validate_scene、构建快照、统一分发与需求情景批算
backend/tests/unit/
  test_provenance.py
  test_scene.py
  test_retail.py
  test_service.py
  test_runner.py
fixtures/
  retail_perishable.json
  retail_durable.json
  appointment_service.json
docs/
  SCENE_SCHEMA.md    # 从 Pydantic 导出/解释契约，禁止前端另造类型
```

修改 README 添加三条直接计算命令与测试说明；确需新增依赖才更新 pyproject 和锁文件。阶段 1 不预建 ORM、Agent 或空前端目录。

## 数据模型约定

下列是待实现规格；不声称模型已存在。金额统一 CNY、单位分；数量为份/件/单，时间为分钟；JSON 使用整数，不通过 float 结算。

| 模型 | 主要字段与约束 |
|---|---|
| `Source` | `user_input / demo_assumption / verified_external / derived / user_observation / unknown` |
| `SourceField[T]` | `value: T或null`、`source`、`note`、可选 `evidence`、`observation_id`、`derived_from`；unknown 当且仅当 value 为 null |
| `ExternalEvidence` | `source_url`（HTTP/HTTPS）、`observed_at`（含时区）、`scope`；verified_external 三者必需。仅存证不发起网络请求；URL 不是真实性保证 |
| `LocationSpec` | `location_type`、`description`、来源证据；兼容草案 `verified=false`，true 必须有核验证据，不等于摆摊许可 |
| `SceneSpec` | `schema_version=1.0`、`business_type`、`title`、`original_idea`、`location`、`fields`、`demand_scenarios`、`unknowns`、`simulation_model_version`；按 business_type 判别联合，禁止多余字段 |
| `RetailFields` | SourceField 包装的 `budget_cents/unit_price_cents/unit_cost_cents/stock_qty/fixed_cost_cents`；易损耗与耐用品共享输入，但输出口径不同 |
| `DemandScenario` | 唯一 `scenario_label`、有来源的 `demand_qty`；低中高只为明确假设，不由售价或 LLM 推算；批算要求标签不重复、假设完整 |
| `ServiceFields` | `unit_price_cents/unit_cost_cents/minutes_per_job/available_minutes/booked/cancelled/fixed_cost_cents`，全部带来源；不强塞库存、零售需求或预付款假设 |
| `ValidationResult` | `valid`、`ready`、机器可读错误与缺失字段路径；草稿结构有效不代表可计算；非法数据和缺失信息分别报告 |
| `RetailInput / ServiceInput` | 从有效草稿与选定情景生成的完整、不可变执行参数；null 不进入公式；预算为 null 时缺口为 null，不影响已知参数的利润计算 |
| `PerishableResult` | `sold/unsold/revenue_cents/cash_out_cents/result_cents/budget_gap_cents` |
| `DurableResult` | `sold/unsold/revenue_cents/cash_out_cents/cash_change_cents/simplified_period_profit_cents/remaining_inventory_cost_cents/budget_gap_cents`；库存成本是账面简化成本，不是可变现价值 |
| `ServiceResult` | `capacity/valid_bookings/completed/revenue_cents/cost_cents/simplified_result_cents/idle_minutes`；不计算未定义的预算缺口 |
| `SimulationSnapshot` | `scene_version_id`、`schema_version`、`model_version`、`input_snapshot`（完整场景、选定假设及来源）、`scenario_label`、类型化 `result`、UTC `calculated_at`；结果来源为 derived 并引用输入路径 |

关键实现细节：

1. 草稿各 SourceField 允许未知；固定成本等不得默认 0。`unknowns` 为字段路径派生的列表，界面文案单独映射。情景标签是输入，不代表预测概率。
2. 数值用严格整数并拒绝 bool、浮点数和数字字符串。拟定技术上限：每个输入金额 0～10^9 分、数量与分钟 0～10^6，每单分钟至少 1；聚合金额保持在 JavaScript 安全整数范围内。这是防误输入的工程限制，不是市场估计。负数输入拒绝，负数经营结果允许；零售价/零成本可表示明确的免费/赠送假设。
3. 取消数不大于预约数。可用分钟 0 合法，每单耗时 0 非法。未知预算不伪造预算结论；已知预算为 0 可产生真实预算缺口。
4. 模型版本分别命名 `retail-perishable-v1`、`retail-durable-v1`、`service-v1`，区分同输入不同核算规则；不匹配业务类型时拒绝计算。schema 版本与公式版本独立管理。
5. 输入字段来源与推导结果分开。derived 必须引用依赖路径；user_observation 必须引用实际观察记录。阶段 1 校验证据形状，阶段 2/4 再验证观察归属和写入权限；结构合法不代表已核实。演示数据不能生成真实观察记录。
6. 纯函数不读时钟、不调用网络、不修改传入对象；快照封装层接受明确版本 ID 与时间，固定输入生成相同结果。冻结对象与深层复制/不可变集合配合，不把 shallow freeze 当不可变版本。
7. 预算检查与公式分开；场地是否允许经营仍可未知，不伪装合规判定。单轮期间与固定成本适用范围写入快照说明。
8. `scene_version_id` 由调用者提供；阶段 1 测试使用明确标记的演示 ID，不假装数据库版本已存在。实际冻结、分支事务和保存发生在阶段 2。

## 计算与测试任务

先落模型与失败测试，再实现既定公式，不引入价格弹性、随机销量或自生成公式。

| 测试组 | 输入或场景 | 必须断言 |
|---|---|---|
| V4 冰粉 A | p=900,c=350,q=30,d=12,f=12000 | sold=12,unsold=18,cash_out=22500,result=-11700（分） |
| V4 冰粉 B | 同上，d=45 | sold=30,unsold=0,result=4500；超库存需求无收入 |
| V4 饰品 | p=1500,c=600,q=20,d=8,f=5000 | cash_change=-5000,period_profit=2200,unsold=12,inventory_cost=7200 |
| V4 摄影 | p=12000,c=2000,job=90,available=360,booked=6,cancelled=1,f=8000 | capacity=4,completed=4,result=32000,idle=0 |
| 零售边界 | d=0、q=0、f=0、d=q、p/c=0 | 销量不超过库存；现金与利润口径正确；unsold+sold=q |
| 预算 | b=0、等于22500、低于22500、高于22500、未知 | gap=max(0,cash_out-b)，未知返回 null；超预算仍可模拟并保留风险依据 |
| 服务边界 | 无预约、全部取消、取消超过预约、不可整除分钟、零可用分钟、零单次分钟 | 超取消/零时长拒绝；完成量不超过有效预约或产能；空闲分钟非负 |
| 严格类型/上限 | -1、1.5、True、"100"、null、超上限、大乘积、1 分 | 非法输入明确拒绝；未知不填 0；整数分无舍入误差；输出安全可序列化 |
| Schema | 三种业务、未知类型/版本、混入另一类字段、额外字段、JSON 往返 | 类型/模型版本一致，跨业务字段拒绝，null 与来源不丢失 |
| 来源 | demo、unknown、缺证据 verified、缺观察引用、derived 无依赖 | 不提升来源；缺元数据拒绝；真实观察授权测试归阶段 2/4 |
| 可复现与快照 | 相同输入多次调用、调用后检查原对象、改售价不改需求 | 结果一致、不变更输入、不擅自调整需求；快照保留参数和来源 |
| 批量情景 | 明确低中高、重复标签、未知 demand | 分别可重算；重复或不完整情景给出字段错误，不静默补数 |
| fixture | 三份显式 demo_assumption 场景 | 同一 runner 路由两类公式；完整校验和 JSON 序列化通过 |

示例中未给预算的算例不虚构预算；预算测试明确提供 b。所有金额和需求均为算例条件，不是真实成本、销量或调研。

阶段 1 验收：pytest 实际执行上述用例，Ruff 和 mypy 通过；三份 fixture 可通过 Python 调用统一 runner 得到结果与快照；说明完整运行命令。不以固定测试数量替代用例覆盖，不将未运行项写成通过。

## 紧接阶段的安排

阶段 1 顺序：来源/严格数值类型 → SceneSpec 与就绪诊断 → 两类纯引擎和预算检查 → 统一 runner/快照/fixtures → 单元测试与运行文档。阶段 1 结束再汇报，不提前加入 LLM 或前端。

V4.0 所列的并发版本创建、重试幂等、数据库持久化和跨用户权限放入阶段 2 集成测试；30 条 Agent 评估在阶段 4 建立用例、阶段 6 汇总。阶段 1 不宣称这些已经验证。
