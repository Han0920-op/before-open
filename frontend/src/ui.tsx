import { Component, useEffect, useRef, useState } from "react";
import type { ErrorInfo, ReactNode } from "react";
import { ApiError, api } from "./lib/api";
import { centsInput, formatCents, parseCents, parseQuantity } from "./lib/money";
import { demandMeta, fieldValue, fieldsFor, missingConditions, scenarioName, setValue, sourceNames } from "./lib/model";
import type { FieldMeta } from "./lib/model";
import type { Preview, Scene, SourceValue } from "./lib/types";

export function navigate(path: string) {
  history.pushState(null, "", path);
  dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo(0, 0);
}

export function Link({ to, children, className }: { to: string; children: ReactNode; className?: string }) {
  return <a href={to} className={className} onClick={(e) => {
    if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) { e.preventDefault(); navigate(to); }
  }}>{children}</a>;
}

export function ErrorCard({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof Error ? error.message : "暂时没有完成，请稍后重试。";
  return <div className="message error" role="alert"><strong>这次还没有完成</strong><p>{message}</p>
    {error instanceof ApiError && error.requestId && <small>反馈编号：{error.requestId}</small>}
    {retry && <button type="button" className="secondary" onClick={retry}>再试一次</button>}</div>;
}

export function Loading() { return <p className="loading" role="status">正在读取你保存的想法……</p>; }

export function useResource<T>(key: string, loader: () => Promise<T>) {
  const [value, setValue] = useState<T>();
  const [error, setError] = useState<unknown>();
  const [revision, setRevision] = useState(0);
  const load = useRef(loader); load.current = loader;
  useEffect(() => {
    let active = true;
    setValue(undefined); setError(undefined);
    load.current().then((v) => { if (active) setValue(v); }).catch((e) => { if (active) setError(e); });
    return () => { active = false; };
  }, [key, revision]);
  return { value, error, reload: () => setRevision((v) => v + 1) };
}

export function useAction() {
  const busy = useRef(false);
  const keys = useRef(new Map<string, string>());
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  function keyFor(path: string, body: unknown) {
    const fingerprint = JSON.stringify([path, body]);
    if (!keys.current.has(fingerprint)) keys.current.set(fingerprint, crypto.randomUUID());
    return keys.current.get(fingerprint)!;
  }
  async function run(action: () => Promise<void>) {
    if (busy.current) return;
    busy.current = true; setPending(true); setError(undefined);
    try { await action(); } catch (e) { setError(e); }
    finally { busy.current = false; setPending(false); }
  }
  return { pending, error, run, keyFor };
}

export function NumberField({ meta, field, onChange }: {
  meta: FieldMeta; field: SourceValue; onChange: (value: number | null, error: string) => void;
}) {
  const [text, setText] = useState(meta.money ? centsInput(field.value) : field.value?.toString() ?? "");
  const [error, setError] = useState("");
  const id = `field-${meta.key}`;
  function change(text: string) {
    setText(text);
    try {
      const value = meta.money ? parseCents(text) : parseQuantity(text, meta.min);
      setError(""); onChange(value, "");
    } catch (e) {
      const message = e instanceof Error ? e.message : "请检查输入";
      setError(message); onChange(null, message);
    }
  }
  const slider = ["stock_qty", "demand_qty", "unit_price_cents"].includes(meta.key);
  return <div className="number-field"><div className="field-heading"><label htmlFor={id}>{meta.label}{meta.money ? "（元）" : ""}</label>
    <span className={`source ${field.source}`}>{sourceNames[field.source]}</span></div>
    <input id={id} type="text" inputMode={meta.money ? "decimal" : "numeric"} value={text}
      autoComplete="off" aria-invalid={Boolean(error)} aria-describedby={`${id}-help`}
      placeholder="还没确定可以先留空" onChange={(e) => change(e.target.value)} />
    {slider && <input type="range" aria-label={`${meta.label}，拖动调整`} min="0"
      max={meta.money ? Math.max(5000, (field.value ?? 0) * 2) : Math.max(100, (field.value ?? 0) * 2)}
      step={meta.money ? 50 : 1} value={field.value ?? 0}
      onChange={(e) => change(meta.money ? centsInput(Number(e.target.value)) : e.target.value)} />}
    <small id={`${id}-help`} className={error ? "field-error" : "muted"}>{error || meta.help}</small>
  </div>;
}

export function ScenarioSelect({ scene, label, onChange }: { scene: Scene; label: string; onChange: (v: string) => void }) {
  if (scene.business_type === "appointment_service") return null;
  return <label className="select-label">这次采用哪组需求假设
    <select value={label} onChange={(e) => onChange(e.target.value)}>
      {scene.demand_scenarios?.map((s) => <option key={s.scenario_label} value={s.scenario_label}>{scenarioName(s.scenario_label)}</option>)}
    </select></label>;
}

export function SceneFields({ scene, label, onChange, onInvalid }: {
  scene: Scene; label: string; onChange: (scene: Scene) => void; onInvalid: (invalid: boolean) => void;
}) {
  const errors = useRef(new Map<string, string>());
  const fields = fieldsFor(scene.business_type);
  if (scene.business_type !== "appointment_service") fields.push(demandMeta);
  return <div className="fields">{fields.map((meta) => <NumberField key={`${label}-${meta.key}`} meta={meta}
    field={fieldValue(scene, meta.key, label)} onChange={(value, error) => {
      if (error) errors.current.set(meta.key, error); else errors.current.delete(meta.key);
      onInvalid(errors.current.size > 0); onChange(setValue(scene, meta.key, value, label));
    }} />)}</div>;
}

export function usePreview(id: string, scene: Scene, label: string, invalid: boolean) {
  const [revision, setRevision] = useState(0);
  const signature = JSON.stringify([id, scene, label, invalid, revision]);
  const [state, setState] = useState<{ key: string; value?: Preview; error?: unknown }>({ key: "" });
  const missing = missingConditions(scene, label);
  const ready = !invalid && !missing.length;
  useEffect(() => {
    const controller = new AbortController();
    if (!ready) return;
    const timeout = setTimeout(() => {
      api.preview(id, scene, label, controller.signal).then((value) => {
        if (!controller.signal.aborted) setState({ key: signature, value });
      }).catch((error) => {
        if (!controller.signal.aborted) setState({ key: signature, error });
      });
    }, 300);
    return () => { clearTimeout(timeout); controller.abort(); };
  }, [signature, ready]);
  return { value: state.key === signature ? state.value : undefined,
    error: state.key === signature ? state.error : undefined, ready, missing,
    retry: () => setRevision((v) => v + 1) };
}

export function Results({ calculation }: { calculation: Preview }) {
  const r = calculation.result;
  const money = (label: string, value: number | null | undefined, primary = false) =>
    <div className={`metric ${primary ? "primary" : ""}`} key={label}><span>{label}</span><strong>{formatCents(value)}</strong></div>;
  const count = (label: string, value: number, unit: string) =>
    <div className="metric" key={label}><span>{label}</span><strong>{value.toLocaleString("zh-CN")}<small>{unit}</small></strong></div>;
  return <section className="results" aria-label="预演结果" aria-live="polite">
    <div className="section-title"><h2>如果按这些条件试一次</h2><span className="source derived">根据公式算出</span></div>
    <div className="metric-grid">
      {r.business_type === "retail_perishable" && <>{money("这轮收支", r.result_cents, true)}{count("能卖出", r.sold, "份")}{count("这一批剩下", r.unsold, "份")}{money("这轮支出", r.cash_out_cents)}{money("营业收入", r.revenue_cents)}{money("预算还差", r.budget_gap_cents)}</>}
      {r.business_type === "retail_durable" && <>{money("这轮现金变化", r.cash_change_cents, true)}{money("简化期间结果", r.simplified_period_profit_cents)}{count("能卖出", r.sold, "件")}{count("还留着", r.unsold, "件")}{money("留存商品的成本", r.remaining_inventory_cost_cents)}{money("预算还差", r.budget_gap_cents)}</>}
      {r.business_type === "appointment_service" && <>{money("这一轮简化结果", r.simplified_result_cents, true)}{count("能完成", r.completed, "单")}{count("最多可服务", r.capacity, "单")}{count("剩余空闲", r.idle_minutes, "分钟")}{money("营业收入", r.revenue_cents)}{money("这轮成本", r.cost_cents)}</>}
    </div>
    <div className="rule-cards" aria-label="条件提醒">
      {r.business_type !== "appointment_service" && r.budget_gap_cents === null && <p className="message">ⓘ 预算还没填，暂时不知道手头的钱够不够。</p>}
      {r.business_type !== "appointment_service" && (r.budget_gap_cents ?? 0) > 0 && <p className="message warning">! 按这组条件，投入还差 {formatCents(r.budget_gap_cents)}。可以试试少备一点，再比较两个方案。</p>}
      {r.business_type === "retail_perishable" && r.unsold > 0 && <p className="message warning">! 这一批还会剩 {r.unsold} 份。这里按“不能留到下一次”计算，整批成本已经发生。</p>}
      {r.business_type === "retail_durable" && r.unsold > 0 && <p className="message">ⓘ 留下的商品仍按原成本保留，所以现金变化和期间结果分开看；不代表一定能按原价卖出。</p>}
      {r.business_type === "appointment_service" && r.valid_bookings > r.capacity && <p className="message warning">! 这组预约超过了可服务容量。未完成的预约没有计入收入，可以试着调整可用时间。</p>}
    </div>
    <p className="muted">这些是条件下的情景推演，不是现实销量或盈利预测。</p>
    <details><summary>查看计算依据</summary><p>{calculation.input_snapshot.period_note}</p>
      <p>规则版本：{calculation.model_version} · 计算时间：{new Date(calculation.calculated_at).toLocaleString("zh-CN")}</p>
      <pre>{JSON.stringify({ inputs: calculation.input_snapshot.fields, demand: calculation.input_snapshot.demand_scenarios, dependencies: calculation.provenance }, null, 2)}</pre>
    </details>
  </section>;
}

export class AppBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(_error: Error, _info: ErrorInfo) { /* Never log user data or input snapshots. */ }
  render() {
    if (this.state.failed) return <main className="page"><ErrorCard error={new Error("页面遇到了问题。已保存的方案仍在，可以重新打开。")} retry={() => location.reload()} /></main>;
    return this.props.children;
  }
}
