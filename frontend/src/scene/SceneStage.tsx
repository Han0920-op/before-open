import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../lib/api";
import { defaultLabel, demandMeta, fieldValue, fieldsFor, setValue } from "../lib/model";
import { formatCents } from "../lib/money";
import type { ProcessView, ProjectDetail, Scene, Version } from "../lib/types";
import { ErrorCard, Link, Loading, NumberField, Results, ScenarioSelect, navigate, useAction, usePreview, useResource } from "../ui";
import { AgentAnalysis } from "../Agent";
import "./scene.css";

type Focus = "price" | "stock" | "conditions";

export function SceneStage({ detail, version, fresh, initialRun }: {
  detail: ProjectDetail; version: Version; fresh: boolean; initialRun?: string;
}) {
  const [scene, setScene] = useState<Scene>(() => structuredClone(version.scene));
  const [label, setLabel] = useState(() => defaultLabel(version.scene));
  const [run, setRun] = useState<ProcessView>();
  const [preparing, setPreparing] = useState(fresh);
  const [focus, setFocus] = useState<Focus>();
  const drawer = useRef<HTMLElement>(null);
  useEffect(() => { if (focus) drawer.current?.scrollIntoView({ block: "nearest", behavior: "instant" }); }, [focus]);
  const [invalid, setInvalid] = useState<Record<string, boolean>>({});
  const [automatic, setAutomatic] = useState(false);
  const [notice, setNotice] = useState("");
  const action = useAction();
  const latest = useResource(`process-${version.id}-${fresh}`, () => fresh ? Promise.resolve([] as ProcessView[]) : api.processes(version.id));
  useEffect(() => { if (latest.value?.[0]) { setRun(latest.value[0]); setLabel(latest.value[0].scenario_label); } }, [latest.value]);
  const editing = preparing || !run;
  const hasInvalid = Object.values(invalid).some(Boolean);
  const preview = usePreview(detail.project.id, scene, label, hasInvalid || !editing);
  const current = !editing ? run?.state : undefined;
  const stock = current?.remaining_stock ?? fieldValue(scene, "stock_qty", label).value;
  const price = fieldValue(scene, "unit_price_cents", label).value;
  const demand = fieldValue(scene, "demand_qty", label).value;
  const distribution = demand == null ? null : [0, 1, 2].map((i) => Math.floor(demand / 3) + (i < demand % 3 ? 1 : 0));
  const cost = preview.value?.result.business_type === "retail_perishable" ? preview.value.result.cash_out_cents : undefined;
  const completed = !editing && run?.status === "completed";
  const stage = editing ? "筹备中" : completed ? "收摊了" : current?.revision === 0 ? "开摊了" : `第 ${current?.revision} 阶段`;

  async function openStall() {
    await action.run(async () => {
      const changed = JSON.stringify(scene) !== JSON.stringify(version.scene);
      const saved = changed ? await api.branch(version.id, scene, action.keyFor("scene-branch", scene)) : version;
      const started = await api.createProcess(saved.id, label, action.keyFor("start-process", [saved.id, label, run?.id]));
      setRun(started); setPreparing(false); setFocus(undefined); setNotice("条件已确认，本轮成本只记入一次。可以逐段营业了。");
      if (saved.id !== version.id || fresh) navigate(`/projects/${detail.project.id}/play?version=${saved.id}`);
    });
  }
  async function advance(kind: "next" | "finish") {
    if (!run) return;
    await action.run(async () => {
      try {
        const next = await api.advanceProcess(run.id, run.state.revision, kind, action.keyFor("advance-process", [run.id, run.state.revision, kind]));
        setRun(next); setNotice(next.state.summary);
        if (next.status === "completed") setAutomatic(false);
      } catch (error) {
        setAutomatic(false);
        if (error instanceof ApiError && error.code === "PROCESS_REVISION_CONFLICT") latest.reload();
        throw error;
      }
    });
  }
  useEffect(() => {
    if (!automatic || editing || completed || action.pending) return;
    const timer = setTimeout(() => { void advance("next"); }, 2400);
    return () => clearTimeout(timer);
  }, [automatic, editing, completed, action.pending, run?.state.revision]);
  function another() {
    setAutomatic(false);
    navigate(`/projects/${detail.project.id}/play?version=${version.id}&prepare=1`);
    setPreparing(true); setFocus("stock"); setNotice("回到筹备另试方案。原来的营业记录保留，新的条件会从头推演。");
  }
  function selectFocus(next: Focus) { setAutomatic(false); setFocus(next); }
  if (latest.error) return <ErrorCard error={latest.error} retry={latest.reload} />;
  if (!latest.value) return <Loading />;
  const group = focus === "price" ? ["unit_price_cents"] : focus === "stock" ? ["stock_qty", "unit_cost_cents"] : ["budget_cents", "fixed_cost_cents", "demand_qty"];
  const metadata = [...fieldsFor(scene.business_type), demandMeta];
  return <>
    <div className="page-title scene-heading"><div><p className="eyebrow">今天，让这个想法开张一次</p><h1>{scene.title}</h1></div><span className="stage-badge">{stage}</span></div>
    <ol className="stage-track" aria-label="营业进度">{["筹备", "开摊", "营业", "收摊"].map((name, index) => <li key={name} aria-current={index === (editing ? 0 : completed ? 3 : current?.revision === 0 ? 1 : 2) ? "step" : undefined}><span>{index + 1}</span>{name}</li>)}</ol>
    <div className="scene-workspace"><section className="scene-main">
      <section className={`market-scene ${!editing && !completed ? "is-open" : ""}`} aria-label="可操作的经营场景">
        <div className="market-sky" aria-hidden="true"><span className="sun"/><span className="cloud cloud-one"/><span className="cloud cloud-two"/></div>
        <div className="campus-building" aria-hidden="true"><i/><i/><i/><i/><i/><i/></div>
        <div className="market-location"><span>周末小市集</span><small>{scene.location.description} · 地点示意</small></div>
        <div className="scene-tree tree-left" aria-hidden="true"/><div className="scene-tree tree-right" aria-hidden="true"/>
        <div className="ground-path" aria-hidden="true"/>
        <div className="stall"><div className="stall-banner">{scene.title}</div><div className="stall-awning" aria-hidden="true"/><div className="stall-poles" aria-hidden="true"/>
          <div className="stall-counter"><div className="cup-display" aria-hidden="true">{Array.from({ length: Math.min(12, stock ?? 0) }, (_, i) => <i className="dessert-cup" key={i}><b/></i>)}</div></div>
          <div className="stall-front"><span>未开张</span><small>BEFORE OPEN · TRY YOUR IDEA</small></div>
        </div>
        <button type="button" className="scene-object price-tag" onClick={() => selectFocus("price")} aria-label="点击价签，调整价格"><small>每份</small><strong>{formatCents(price)}</strong><span>{editing ? "点击定价 ↗" : "查看价格 ↗"}</span></button>
        <button type="button" className="scene-object stock-crate" onClick={() => selectFocus("stock")} aria-label="点击备货箱，调整备货"><span aria-hidden="true">▤</span><strong>{stock ?? "待定"} 份</strong><small>{editing ? "点击备货 ↗" : "当前库存 ↗"}</small></button>
        <button type="button" className="scene-object condition-board" onClick={() => selectFocus("conditions")} aria-label="点击告示牌，查看经营条件">本轮条件 <span>↗</span></button>
        <div className="customer-group" aria-hidden="true">{current && current.revision > 0 && !completed && Array.from({ length: Math.min(3, run?.steps[current.revision]?.demand ?? 0) }, (_, i) => i).map((i) => <i className="customer" key={i}/>)}</div>
        <span className="scene-caption">{editing ? "点点价签和备货箱，准备你的小摊" : completed ? "今天的推演结束了，看看下一次能怎么做" : "画面随营业记录变化，点下一阶段继续"}</span>
      </section>
      <p className="scene-disclosure">顾客符号是示意，不代表实际人流。库存以数字为准；分段需求为演示分配，不是销量预测。</p>
      <div className="live-metrics" aria-label="当前营业状态" aria-live="polite">
        <div><span>已卖出</span><strong>{current?.sold ?? 0}<small>份</small></strong></div><div><span>还剩下</span><strong>{stock ?? "待定"}<small>份</small></strong></div>
        <div><span>累计收入</span><strong>{formatCents(current?.revenue_cents ?? 0)}</strong></div><div><span>{editing ? "预计本轮支出" : "本轮已支出"}</span><strong>{formatCents(editing ? cost : current?.cash_out_cents)}</strong></div>
      </div>
      {notice && <p className="message" role="status">{notice}</p>}
      {action.error != null && <ErrorCard error={action.error} />}
      {!editing && run && <div className="process-controls">
        {!completed && <><button disabled={action.pending} onClick={() => { setAutomatic(false); void advance("next"); }}>{action.pending ? "正在推进……" : "下一阶段 →"}</button>
          <button className="secondary" disabled={action.pending} onClick={() => setAutomatic((v) => !v)}>{automatic ? "暂停自动播放" : "自动播放"}</button>
          <button className="secondary" disabled={action.pending} onClick={() => { setAutomatic(false); void advance("finish"); }}>直接看完整结算</button></>}
        <button className="secondary" disabled={action.pending} onClick={another}>回到筹备，另试方案</button>
      </div>}
      {!editing && run && <details className="card process-ledger"><summary>查看本轮营业记录（已保存）</summary><ol>{run.steps.map((step) => <li key={step.sequence}><strong>{step.sequence === 0 ? "筹备" : `营业 ${step.sequence}`}</strong><p>{step.after.summary}</p><small>本步收入 {formatCents(step.revenue_cents)} · 本步支出 {formatCents(step.cash_out_cents)}</small></li>)}</ol>
        <p>过程规则：{run.profile.rule_version} · 推演记录：{run.id}</p><p>{run.profile.note}</p>
        {current?.budget_balance_cents != null && <p>按已填预算与本轮收支计算，手头剩余：{formatCents(current.budget_balance_cents)}。这不是利润。</p>}
      </details>}
      {completed && run?.calculation && <><section className="card closing-note"><p className="eyebrow">收摊后，想明白一件事</p><h2>今天这个选择，带来了什么？</h2><p>本轮售出 {current?.sold} 份，剩余 {stock} 份。按这批未售商品无法保留的假设，整批成本已发生。</p><div className="actions"><Link to={`/projects/${detail.project.id}/compare`}>比较两个方案 →</Link><Link to={`/projects/${detail.project.id}/experiment`}>去现实里验证一个条件 →</Link></div></section><Results calculation={run.calculation}/>
        <AgentAnalysis project={detail.project.id} version={version} label={run.scenario_label} {...(initialRun ? { initialRun } : {})}/></>}
    </section>
    <aside className="scene-sidebar">
      {editing ? <section className="card opening-card"><p className="eyebrow">先准备，再开摊</p><h2>这一次，想怎么试？</h2><p>点场景中的价签和备货箱修改条件，也可以直接使用已确认的条件。</p>
        <div className="scene-shortcuts"><button className="secondary" onClick={() => selectFocus("price")}>定价格</button><button className="secondary" onClick={() => selectFocus("stock")}>备多少货</button><button className="secondary" onClick={() => selectFocus("conditions")}>其他条件</button></div>
        <ScenarioSelect scene={scene} label={label} onChange={(next) => { setLabel(next); setInvalid({}); }}/>
        <div className="message"><strong>确认本次过程假设</strong><p>总需求 {demand ?? "待确认"} 份，按 {distribution?.join(" / ") ?? "待确认"} 分到三个逻辑阶段；阶段不代表实际钟点。</p><small>点击开摊即确认这项演示分配。需求来源保留在“查看全部条件”中。</small></div>
        {!preview.ready && <p className="field-error">{hasInvalid ? "请修正输入后再开摊。" : `还需要确认：${preview.missing.join("、")}`}</p>}
        {preview.error != null && <ErrorCard error={preview.error} retry={preview.retry}/>}
        {preview.value?.result.business_type === "retail_perishable" && (preview.value.result.budget_gap_cents ?? 0) > 0 && <p className="message warning">按这次备货，预算还差 {formatCents(preview.value.result.budget_gap_cents)}。你可调整备货，或明确在假设中继续。</p>}
        <button className="open-button" disabled={!preview.value || hasInvalid || action.pending} onClick={() => void openStall()}>{action.pending ? "正在准备营业……" : "确认条件，开摊 →"}</button>
        <p className="muted">这是推演台账，不会发生实际付款。改动的条件会保存为独立方案。</p>
      </section> : <section className="card opening-card"><p className="eyebrow">{completed ? "这一轮已经结束" : "经营正在发生"}</p><h2>{completed ? "下一次，试个不同选择" : "看看这一段会怎样"}</h2><p>{current?.summary}</p><p>本轮需求分配：{run?.profile.demand_by_stage.join(" / ")}。</p><p className="muted">营业中的价格与备货已固定。要修改，可回到筹备另开一个方案，原来的记录保留。</p>{completed && <button onClick={another}>再试一种备货方案</button>}</section>}
      {focus && <section ref={drawer} className="card preparation-drawer" aria-label="经营条件编辑"><div className="section-title"><h2>{focus === "price" ? "给商品定个价格" : focus === "stock" ? "准备这一批商品" : "本轮经营条件"}</h2><button className="secondary" onClick={() => setFocus(undefined)}>收起</button></div>
        {editing ? <>{metadata.filter((m) => group.includes(m.key)).map((meta) => <NumberField key={`${label}-${meta.key}`} meta={meta} field={fieldValue(scene, meta.key, label)} onChange={(value, error) => { setScene((s) => setValue(s, meta.key, value, label)); setInvalid((v) => ({...v, [meta.key]: Boolean(error)})); }}/>)}</> : <><p>营业中的条件已固定。你可以从头另试，比较选择带来的不同。</p><button className="secondary" disabled={action.pending} onClick={another}>回到筹备修改条件</button></>}
      </section>}
      <details className="card scene-evidence"><summary>查看全部条件与来源</summary><p>{scene.period_note}</p><pre>{JSON.stringify({ fields: scene.fields, demand: scene.demand_scenarios }, null, 2)}</pre><Link to={`/projects/${detail.project.id}/setup`}>调整场景说明 →</Link></details>
    </aside></div>
  </>;
}
