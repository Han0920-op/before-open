# SceneSpec 1.0 与经营计算契约

本阶段的事实来源是 `backend/app/schemas/` 中的 Pydantic 模型；[scene.schema.json](scene.schema.json) 由 `scene_adapter.json_schema()` 生成，单元测试保证导出文件与模型一致。跨字段/来源等程序校验不能只靠 JSON Schema 替代。没有手写另一套前端类型。

## 输入、未知与来源

根字段：`schema_version=1.0`、`currency=CNY`、`business_type`、`title`、`original_idea`、`location`、`period_note`、`fields`、`demand_scenarios`、`simulation_model_version`、`unknowns`。

- `business_type` 判别三种模型，额外字段、跨业务字段、未知业务类型/版本均拒绝。
- `period_note` 明确单次模拟期间、固定成本计入范围与简化边界，不从用户原话推断经济规则。
- `unknowns` 由模型重算为数字字段与需求假设的缺失路径；即使客户端传入旧列表也不会隐藏实际缺失。地点核验状态独立保留，不因可计算而变为已核验。
- 标题和地点描述用于呈现，不能当作经营许可或外部事实。地点 `verified=true` 需 source 为 verified_external 且有证据；用户观察需 observation_id，派生描述需 derived_from。

每个经营输入为 `SourceField[T]`，包含 `value/source/note/evidence/observation_id/derived_from`：

| source | 强制条件 |
|---|---|
| unknown | value=null；禁止塞入证据、观察引用或派生依赖 |
| user_input / demo_assumption | 值明确；不能携带其他来源专用的证据标记 |
| verified_external | 明确值＋source_url（HTTP/HTTPS）＋含时区 observed_at＋scope |
| user_observation | 明确值＋非空 observation_id |
| derived | 明确值＋非空 derived_from 路径列表 |

**这里只验证数据结构，不核验真实世界或写入权限。** 链接不是可信证明，观察 ID 的存在与归属、Agent 是否有权声明来源将在后续服务端入口校验。引擎不联网，也不提升任何输入的 source。

金额必须是 JSON 整数分，0～10^9；数量与可用分钟为整数 0～10^6，单次服务分钟为整数 1～10^6。bool、float、数字字符串、负数和超上限拒绝。0 表示明确的零价/零成本假设，null 才表示未知。结果允许负数，且限制在 ±(2^53−1) 以内以便后续 JavaScript 精确表示。

## 三种场景

| business_type / model_version | fields | 需求条件 |
|---|---|---|
| retail_perishable / retail-perishable-v1 | budget_cents、unit_price_cents、unit_cost_cents、stock_qty、fixed_cost_cents | demand_scenarios 中的 scenario_label 与有来源的 demand_qty |
| retail_durable / retail-durable-v1 | 同上 | 同上；标签唯一，允许多个明示需求假设 |
| appointment_service / service-v1 | unit_price_cents、unit_cost_cents、minutes_per_job、available_minutes、booked、cancelled、fixed_cost_cents | 预约与取消即本次假设，不接受零售 demand_scenarios |

所有字段包装都必须存在，但草稿的 value 可未知。`validate_scene` 区分结构错误（valid=false）和缺少计算参数（valid=true, ready=false），返回错误与字段路径。预算未知仍可计算利润，budget_gap_cents=null；其他必需计算参数未知会阻止计算，不补 0。

零售 `validate_scene(scene, label)` 只检查选中需求和公共参数；不带标签则检查全部需求。调用 simulate 必须选择已有标签；不存在的标签为 INVALID_SCENE，空/不完整的整批需求为 SIMULATION_NOT_READY。服务的 scenario_label 仅作这份预约条件的记录标签。

## 公式与结果口径

- 易损耗：sold=min(q,d)，unsold=q−sold，revenue=sold×p，cash_out=q×c+f，result=revenue−cash_out。前提是整批成本已发生且剩余商品不能保留。
- 可保留：同样的销量和现金支出；cash_change=revenue−cash_out，simplified_period_profit=revenue−sold×c−f，remaining_inventory_cost=unsold×c。不把库存成本当作可变现价值，不把现金变化直接称为利润。
- 两类零售预算缺口：max(0,cash_out−budget)，预算未知为 null；超预算不阻止模拟。
- 服务：capacity=available_minutes//minutes_per_job，valid_bookings=booked−cancelled，completed=min(capacity,valid_bookings)，revenue=completed×p，cost=completed×c+f，simplified_result=revenue−cost，idle_minutes=available_minutes−completed×minutes_per_job。cancelled>booked 在计算前拒绝。

实际结果键名及单位见 `schemas/simulation.py`（金额键均以 `_cents` 结尾）。不自动加入税、押金、退款、交通费、存货跌价或需求弹性；摄影时长是否包含拍摄/后期，由用户在明确期间和时间假设中给出。

## 调用与快照

- `calculate_perishable(RetailInput)`、`calculate_durable(RetailInput)`、`calculate_service(ServiceInput)`：接收完整校验后的执行参数，纯函数，无网络/时钟/随机数/数据库。
- `check_budget(budget_cents, cash_out_cents)`：预算与付款分开校验，未知预算返回 null，不判断场地合规或服务预付款。
- `simulate(scene, scene_version_id=..., scenario_label=..., calculated_at=...)`：统一校验、分发和封装快照。调用者传入明确版本和含时区时间；输出时间规范为 UTC。
- `preview(scene, scenario_label=..., calculated_at=...)`：阶段 3 增加的同一计算链的草稿入口，返回 CalculationPreview，不携带业务版本 ID、不做持久化；simulate 在该结果上封装真实 scene_version_id。原公式不变。
- `run_demand_scenarios`：零售显式需求的整批计算；整批输入不完整时拒绝，不返回一半结果。服务不适用这个入口。
- `replay_snapshot`：按已保存输入与当前支持的模型版本重算，并对结果、来源依赖和整个封装逐项比较，篡改时拒绝。

快照保存 `scene_version_id/schema_version/model_version/input_snapshot/scenario_label/result/provenance/calculated_at`。`input_snapshot` 保留完整场景、来源、选中标签对应的需求及其他候选需求；`provenance` 为每个数字结果记录 source 和依赖路径（相对于 input_snapshot）。已知结果为 derived，未知预算缺口为 unknown。输入的 demo 或用户观察不会因参与计算而升级为外部核验。

嵌套 Pydantic 对象冻结，序列使用 tuple，原始字典修改不会影响快照。`parse_scene` 会重校验已有对象，防止未校验的 model_copy 更新进入 runner。**快照类型校验不是计算证明**；读取外来快照须使用 replay_snapshot 重算，而不是仅 model_validate 后信任其数字。将来添加模型版本时必须保留旧版本处理器，不覆盖旧版公式。

本阶段无真实版本库、事务或观察记录库，CLI 中 demo-* 为显式演示 ID。不可变业务版本、幂等、所有权、数据保存与 HTTP 错误契约在阶段 2 完成。

## 重建导出的 Schema

在 backend 目录运行，变更模型后应重新导出：

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
from app.schemas.scene import scene_adapter

Path('../docs/scene.schema.json').write_text(
    json.dumps(scene_adapter.json_schema(), ensure_ascii=False, indent=2) + '\n'
)
PY
```

fixtures 提供可校验样例；README 包含三条直接计算命令。所有样例是假设，不构成现实销量或盈利承诺。
