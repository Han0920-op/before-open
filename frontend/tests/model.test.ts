import { describe, expect, it } from "vitest";
import { defaultLabel, draft, fieldValue, fieldsFor, missingConditions, setValue } from "../src/lib/model";
import type { BusinessType, Project } from "../src/lib/types";

const project: Project = { id: "demo", title: "测试想法", original_idea: "用户的原句，不能替换", created_at: "2026-10-24T00:00:00Z" };
const kinds: BusinessType[] = ["retail_perishable", "retail_durable", "appointment_service"];

describe("shared dynamic scene configuration", () => {
  it.each(kinds)("keeps %s custom drafts unknown", (kind) => {
    const scene = draft(kind, project, false);
    expect(scene.original_idea).toBe(project.original_idea);
    expect(scene.location.verified).toBe(false);
    expect(missingConditions(scene, defaultLabel(scene)).length).toBeGreaterThan(0);
    for (const metadata of fieldsFor(kind)) {
      const field = fieldValue(scene, metadata.key, defaultLabel(scene));
      expect(field.value).toBeNull(); expect(field.source).toBe("unknown");
    }
  });
  it.each(kinds)("uses explicit demo provenance for %s", (kind) => {
    const scene = draft(kind, project, true);
    expect(missingConditions(scene, defaultLabel(scene))).toEqual([]);
    expect(fieldValue(scene, "unit_price_cents", defaultLabel(scene)).source).toBe("demo_assumption");
  });
  it("changing price preserves demand, original and the parent object", () => {
    const scene = draft("retail_perishable", project, true), before = structuredClone(scene);
    const next = setValue(scene, "unit_price_cents", 999, "low");
    expect(scene).toEqual(before); expect(next.demand_scenarios).toEqual(scene.demand_scenarios);
    expect(fieldValue(next, "unit_price_cents", "low").source).toBe("user_input");
    expect(next.original_idea).toBe(project.original_idea);
  });
  it("updates only the selected demand scenario", () => {
    const scene = draft("retail_perishable", project, true);
    const next = setValue(scene, "demand_qty", 6, "low");
    expect(fieldValue(next, "demand_qty", "low").value).toBe(6);
    expect(fieldValue(next, "demand_qty", "high").value).toBe(45);
  });
  it("treats budget as optional and rejects excessive cancellation before preview", () => {
    const retail = draft("retail_durable", project, true);
    expect(fieldValue(retail, "budget_cents", "base").value).toBeNull();
    expect(missingConditions(retail, "base")).toEqual([]);
    const service = setValue(draft("appointment_service", project, true), "cancelled", 7, "base");
    expect(missingConditions(service, "base")).toContain("取消数不能超过预约数");
  });
});
