import fixtures from "../generated/fixtures.json";
import type { BusinessType, Project, Scene, Source, SourceValue } from "./types";

export const businessNames: Record<BusinessType, string> = {
  retail_perishable: "卖当天用完的商品", retail_durable: "卖可以留下的商品",
  appointment_service: "按预约提供服务",
};
export const sourceNames: Record<Source, string> = {
  user_input: "你填写的", demo_assumption: "演示假设", verified_external: "资料已核实",
  derived: "根据公式算出", user_observation: "你记录的现实观察", unknown: "待确认",
};
export const examples = [
  { kind: "retail_perishable", name: "卖冰粉", icon: "◒", idea: "我想在学校周末市集卖冰粉，预算 500 元。" },
  { kind: "retail_durable", name: "做手工饰品", icon: "✧", idea: "我想在周末创意市集卖手工耳饰，预算 300 元。" },
  { kind: "appointment_service", name: "接宠物摄影订单", icon: "▣", idea: "周末想接宠物摄影订单，每单 99 元，只有半天时间。" },
] as const;

export type FieldMeta = { key: string; label: string; money?: boolean; min?: number; help: string };
const price: FieldMeta = { key: "unit_price_cents", label: "每份卖多少钱", money: true, help: "单位：元；调整价格不会自动改变需求假设。" };
const cost: FieldMeta = { key: "unit_cost_cents", label: "每份成本", money: true, help: "单位：元；不确定可以留空，不会替你补造。" };
const fixed: FieldMeta = { key: "fixed_cost_cents", label: "这一次的固定费用", money: true, help: "如本次摊位费；确实没有时请填 0。" };
const stock: FieldMeta = { key: "stock_qty", label: "今天准备多少份", help: "非负整数；超过备货的需求不会转成收入。" };
export const demandMeta: FieldMeta = { key: "demand_qty", label: "这次假设有多少份需求", help: "这是你设定的条件，不是现实销量预测。" };

export function fieldsFor(kind: BusinessType): FieldMeta[] {
  if (kind !== "appointment_service") return [
    { key: "budget_cents", label: "手头可以投入的钱", money: true, help: "单位：元；未知时只计算结果，不判断预算够不够。" },
    price, cost, stock, fixed,
  ];
  return [
    { ...price, label: "每单收费" }, { ...cost, label: "每单成本" },
    { key: "minutes_per_job", label: "完成一单要多少分钟", min: 1, help: "把需要的拍摄、后期等时间一起算入。" },
    { key: "available_minutes", label: "这次总共能用多少分钟", help: "例如半天为多少分钟，由你明确填写。" },
    { key: "booked", label: "假设收到多少单预约", help: "你填写的预约情景，不是实际获客预测。" },
    { key: "cancelled", label: "其中取消多少单", help: "不能超过预约单数，不自动生成现实取消率。" }, fixed,
  ];
}

export function values(scene: Scene): Record<string, SourceValue> {
  return scene.fields as unknown as Record<string, SourceValue>;
}

export function fieldValue(scene: Scene, key: string, label: string): SourceValue {
  if (key === "demand_qty" && scene.business_type !== "appointment_service") {
    return scene.demand_scenarios?.find((s) => s.scenario_label === label)?.demand_qty
      ?? { value: null, source: "unknown", note: "还没有填写", derived_from: [] };
  }
  return values(scene)[key] ?? { value: null, source: "unknown", note: "还没有填写", derived_from: [] };
}

export function setValue(scene: Scene, key: string, value: number | null, label: string): Scene {
  const field: SourceValue = { value, source: value === null ? "unknown" : "user_input", note: "你手动填写的条件", derived_from: [] };
  if (key === "demand_qty" && scene.business_type !== "appointment_service") return {
    ...scene, demand_scenarios: scene.demand_scenarios?.map((s) => s.scenario_label === label
      ? { ...s, demand_qty: field } : s) ?? [],
  };
  return { ...scene, fields: { ...scene.fields, [key]: field } } as Scene;
}

export function defaultLabel(scene: Scene): string {
  return scene.business_type === "appointment_service" ? "base" : scene.demand_scenarios?.[0]?.scenario_label ?? "base";
}

export function draft(kind: BusinessType, project: Project, demo: boolean): Scene {
  // Fixtures are generated from the backend-validated canonical JSON, not separately authored.
  const scene = structuredClone(fixtures[kind]) as unknown as Scene;
  scene.original_idea = project.original_idea;
  scene.title = demo ? fixtures[kind].title : project.title;
  for (const field of Object.values(values(scene))) field.derived_from ??= [];
  scene.location.derived_from ??= [];
  for (const scenario of scene.demand_scenarios ?? []) scenario.demand_qty.derived_from ??= [];
  if (!demo) {
    for (const field of Object.values(values(scene))) {
      field.value = null; field.source = "unknown"; field.note = "还没有填写";
    }
    scene.location = { location_type: "user_defined", description: "待填写的经营地点", source: "unknown", verified: false, derived_from: [] };
    scene.period_note = "本次预演；固定费用只计一次。不含税务、押金、退款等复杂项目。";
    if (scene.business_type !== "appointment_service") {
      scene.demand_scenarios = [{ scenario_label: "base", demand_qty: { value: null, source: "unknown", note: "还没有填写", derived_from: [] } }];
    }
  }
  return scene;
}

export function missingConditions(scene: Scene, label: string): string[] {
  const fields = fieldsFor(scene.business_type).filter((m) => m.key !== "budget_cents");
  if (scene.business_type !== "appointment_service") fields.push(demandMeta);
  const missing = fields.filter((m) => fieldValue(scene, m.key, label).value == null).map((m) => m.label);
  if (scene.business_type === "appointment_service") {
    const { booked, cancelled } = scene.fields;
    if (booked.value != null && cancelled.value != null && cancelled.value > booked.value) missing.push("取消数不能超过预约数");
  }
  return missing;
}

export function scenarioName(label: string): string {
  return ({ low: "少一点（需求假设）", medium: "中间情景（需求假设）", high: "多一点（需求假设）", base: "当前假设" } as Record<string, string>)[label] ?? label;
}
