import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "./lib/api";
import { businessNames, defaultLabel, draft, examples, fieldsFor, fieldValue, missingConditions, sourceNames } from "./lib/model";
import { parseCents, parseQuantity, formatCents } from "./lib/money";
import type { BusinessType, Comparison, ProjectDetail, Scene, Summary, Version } from "./lib/types";
import { AppBoundary, ErrorCard, Link, Loading, Results, ScenarioSelect, SceneFields,
  navigate, useAction, usePreview, useResource } from "./ui";

import { AgentSetup, AgentAnalysis, ExperimentAssistant } from "./Agent";
import { SceneStage } from "./scene/SceneStage";

const kinds: BusinessType[] = ["retail_perishable", "retail_durable", "appointment_service"];

function ProjectNav({ id, active }: { id: string; active: string }) {
  return <nav className="project-nav" aria-label="想法的预演步骤">{[
    ["setup", "1 准备条件"], ["play", "2 亲手试试"], ["compare", "3 比比方案"], ["experiment", "4 现实挑战"],
  ].map(([path, name]) => <Link key={path} to={`/projects/${id}/${path}`} className={active === path ? "active" : ""}>{name}</Link>)}</nav>;
}

function Home() {
  const [idea, setIdea] = useState("");
  const [example, setExample] = useState<BusinessType>();
  const action = useAction();
  function start(event: FormEvent) {
    event.preventDefault();
    if (!idea.trim()) return;
    void action.run(async () => {
      const original = idea.trim();
      const project = await api.createProject(original, original.slice(0, 28), action.keyFor("create-project", original));
      navigate(`/projects/${project.id}/setup${example ? `?example=${example}` : ""}`);
    });
  }
  return <main id="main" className="page home"><section className="hero-copy"><p className="eyebrow">一个小想法，也值得认真试试</p>
    <h1>如果你的奇思妙想，<br /><em>真的开张了呢？</em></h1>
    <p className="lead">说出你想做的小生意，搭个能亲手试的场景。</p>
    <form onSubmit={start} className="idea-form"><label htmlFor="idea">你想试试什么？</label>
      <textarea id="idea" maxLength={10000} rows={4} required value={idea} onChange={(e) => { setIdea(e.target.value); setExample(undefined); }}
        placeholder="例如：我想在学校周末市集卖冰粉，预算 500 元。" />
      <div className="form-footer"><span>说出想法，准备好条件就能亲手试营业。</span><button disabled={action.pending || !idea.trim()}>{action.pending ? "正在保存想法……" : "开始预演 →"}</button></div>
    </form>
    {action.error != null && <ErrorCard error={action.error} />}
    <div className="examples" aria-label="快速例子">{examples.map((e) => <button className="example" type="button" key={e.kind}
      onClick={() => { setIdea(e.idea); setExample(e.kind); }}><span aria-hidden="true">{e.icon}</span>{e.name}<small>使用演示条件</small></button>)}</div>
    <p className="trust">ⓘ 这里展示的是情景推演，不是现实销量预测。</p>
  </section><aside className="hero-scene" aria-label="创意场景示意"><div className="paper-note">今天，先试一种可能。</div>
    <div className="awning"><i /><i /><i /><i /><i /></div><div className="store-window"><span>◒</span><span>✧</span><span>▣</span></div>
    <div className="store-front">未开张<span>BEFORE OPEN</span></div><div className="scene-caption">一份想法 · 几个条件 · 多一种选择</div>
  </aside></main>;
}

function Projects() {
  const [offset, setOffset] = useState(0);
  const resource = useResource(`projects-${offset}`, () => api.projects(offset));
  return <main id="main" className="page"><div className="page-title"><div><p className="eyebrow">慢慢想，随时回来</p><h1>我的想法</h1></div><Link className="button" to="/">再试一个想法</Link></div>
    <p className="muted">这个浏览器会记住你的匿名身份。清理浏览器数据或换设备后，可能找不回原来的想法。</p>
    {resource.error ? <ErrorCard error={resource.error} retry={resource.reload} /> : !resource.value ? <Loading /> : <>
      {!resource.value.length && <div className="empty"><h2>这里还有很多可能</h2><p>先写下一句话，给它搭个小场景。</p><Link to="/" className="button">开始第一个预演</Link></div>}
      <div className="project-grid">{resource.value.map((p) => <article className="card" key={p.id}><span className="source">已保存</span><h2>{p.title}</h2><p>{p.original_idea}</p><small>{new Date(p.created_at).toLocaleDateString("zh-CN")}</small><Link className="text-link" to={`/projects/${p.id}/play`}>继续看看 →</Link></article>)}</div>
      <div className="actions"><button className="secondary" disabled={offset === 0} onClick={() => setOffset((v) => v - 50)}>上一页</button><button className="secondary" disabled={resource.value.length < 50} onClick={() => setOffset((v) => v + 50)}>下一页</button></div>
    </>}
  </main>;
}

function Setup({ detail, example }: { detail: ProjectDetail; example?: BusinessType }) {
  const latest = detail.versions.at(-1);
  const [scene, setScene] = useState<Scene>(() => latest?.scene ?? draft(example ?? "retail_perishable", detail.project, Boolean(example)));
  const [label, setLabel] = useState(() => defaultLabel(scene));
  const [generation, setGeneration] = useState(0);
  const [invalid, setInvalid] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const action = useAction();
  function reset(kind: BusinessType, demo: boolean) {
    const next = draft(kind, detail.project, demo);
    setScene(next); setLabel(defaultLabel(next)); setInvalid(false); setGeneration((v) => v + 1);
  }
  function save(event: FormEvent) {
    event.preventDefault();
    void action.run(async () => {
      const version = latest
        ? await api.branch(latest.id, scene, action.keyFor(`branch-${latest.id}`, scene))
        : await api.confirm(detail.project.id, scene, action.keyFor(`confirm-${detail.project.id}`, scene));
      navigate(`/projects/${detail.project.id}/play?version=${version.id}`);
    });
  }
  const missing = missingConditions(scene, label);
  return <><div className="page-title"><div><p className="eyebrow">先把条件摆在桌上</p><h1>准备你的专属场景</h1></div></div>
    <p className="idea-quote">“{detail.project.original_idea}”</p>
    <AgentSetup project={detail.project.id} autoStart={!example && !latest} onUseScene={(next) => { setScene(next); setLabel(defaultLabel(next)); setInvalid(false); setGeneration((v) => v + 1); }} />
    <form onSubmit={save}>
    <section className="card setup-confirm"><h2>确认这一次，想怎么试</h2><div className="setup-overview">{fieldsFor(scene.business_type).filter((m) => fieldValue(scene, m.key, label).value != null).map((m) => { const f = fieldValue(scene, m.key, label); return <span key={m.key}>{m.label}：{m.money ? formatCents(f.value) : f.value} · {sourceNames[f.source]}</span>; })}</div>
    <ScenarioSelect scene={scene} label={label} onChange={(next) => { setLabel(next); setInvalid(false); }} />
    <p className="muted">{missing.length ? `还需要确认：${missing.join("、")}。可展开自己填写，或主动选择演示条件。` : "条件已齐，可以开始。进入场景后也能调整价格与备货。"}</p>
    <div className="actions"><button type="button" className="secondary" onClick={() => { reset(scene.business_type, true); setExpanded(false); }}>用演示条件先试试</button><button type="button" className="secondary" onClick={() => setExpanded((v) => !v)}>{expanded ? "收起经营条件" : "自己填写或调整条件"}</button></div><p className="muted">演示数字不是你的真实成本、销量或调研结论。未知预算可留空。</p></section>
    <details className="setup-collapsed" open={expanded} onToggle={(e) => setExpanded(e.currentTarget.open)}><summary>展开全部经营条件与来源</summary><div className="setup-grid"><section className="card"><h2>想怎么试一次？</h2>
      <label>经营方式<select value={scene.business_type} onChange={(e) => {
        if (window.confirm("切换经营方式会清空未保存的条件，要继续吗？")) reset(e.target.value as BusinessType, false);
      }}>{kinds.map((kind) => <option key={kind} value={kind}>{businessNames[kind]}</option>)}</select></label>
      <label>给这个场景起个名字<input value={scene.title} maxLength={200} required onChange={(e) => setScene({ ...scene, title: e.target.value })} /></label>
      <label>在哪里试？<input value={scene.location.description} required onChange={(e) => setScene({ ...scene, location: { location_type: "user_defined", description: e.target.value, source: "user_input", verified: false, derived_from: [] } })} /></label>
      <p className="muted">地点未核实。是否允许经营、是否需要许可，请向现场管理方确认。</p>
      <label>这次预演的时间和费用范围<textarea rows={3} required value={scene.period_note} onChange={(e) => setScene({ ...scene, period_note: e.target.value })} /></label>
      <div className="message"><strong>不确定也没关系</strong><p>未知的成本可以先留空。只有在条件补齐后才会给出计算结果。</p></div>

      <p className="muted">演示数字不是你的真实成本或销量；加载后会保留清晰的“演示假设”标记。</p>
    </section><section className="card"><h2>这一次，先定下这些条件</h2>
      <SceneFields key={`${generation}-${label}`} scene={scene} label={label} onChange={setScene} onInvalid={setInvalid} />
    </section></div></details>
      {action.error != null && <ErrorCard error={action.error} />}
      <p className="muted">点击下方按钮会保存独立方案；以后修改不会覆盖旧版本。</p>
      <button disabled={invalid || missing.length > 0 || action.pending || !scene.title.trim() || !scene.location.description.trim() || !scene.period_note.trim()}>{action.pending ? "正在保存……" : "确认这些条件，开始预演 →"}</button>
    </form></>;
}

function Sandbox({ detail, version, initialRun }: { detail: ProjectDetail; version: Version; initialRun?: string }) {
  const [scene, setScene] = useState<Scene>(() => structuredClone(version.scene));
  const [label, setLabel] = useState(() => defaultLabel(scene));
  const [invalid, setInvalid] = useState(false);
  const [saved, setSaved] = useState(false);
  const action = useAction();
  const preview = usePreview(detail.project.id, scene, label, invalid);
  const changed = JSON.stringify(scene) !== JSON.stringify(version.scene);
  async function save() {
    const next = changed ? await api.branch(version.id, scene, action.keyFor(`branch-${version.id}`, scene)) : version;
    await api.simulate(next.id, label, action.keyFor(`simulate-${next.id}`, label));
    if (changed) navigate(`/projects/${detail.project.id}/play?version=${next.id}`);
    else setSaved(true);
  }
  return <><div className="page-title"><div><p className="eyebrow">不急着开张，先试几种可能</p><h1>{scene.title}</h1></div><span className="source">方案 {detail.versions.findIndex((v) => v.id === version.id) + 1}</span></div>
    <div className="sandbox-grid"><section className="card controls"><h2>如果这样做呢？</h2><p className="muted">拖动或填写条件，结果会按服务端公式更新。保存前不会创建新版本。</p>
      <ScenarioSelect scene={scene} label={label} onChange={(v) => { setLabel(v); setInvalid(false); setSaved(false); }} />
      <SceneFields key={`${version.id}-${label}`} scene={scene} label={label} onChange={(v) => { setScene(v); setSaved(false); }} onInvalid={setInvalid} />
      {action.error != null && <ErrorCard error={action.error} />}
      <button disabled={!preview.ready || invalid || action.pending} onClick={() => void action.run(save)}>{action.pending ? "正在保存……" : changed ? "保存为新方案" : "保存这次预演结果"}</button>
      {saved && <p role="status" className="success">✓ 这次预演结果已保存。</p>}
      <div className="actions"><Link to={`/projects/${detail.project.id}/compare`}>比比方案 →</Link><Link to={`/projects/${detail.project.id}/setup`}>修改场景信息</Link></div>
    </section><div className="result-column">
      {!preview.ready ? <section className="empty"><span className="empty-icon" aria-hidden="true">✎</span><h2>还差一点条件，就能试算了</h2><p>{invalid ? "请先修正标红的输入。" : `请补充：${preview.missing.join("、")}`}</p><p className="muted">未知的数据会保持未知，不会替你猜一个答案。</p></section>
        : preview.error ? <ErrorCard error={preview.error} retry={preview.retry} /> : preview.value ? <Results calculation={preview.value} /> : <p className="loading" role="status">正在按这组条件试算……</p>}
      <AgentAnalysis project={detail.project.id} version={version} label={defaultLabel(version.scene)} {...(initialRun ? { initialRun } : {})} />
      <section className="card next-step"><h2>下一步，找一个真实的人聊聊</h2><p>这里能算清条件，却不能替你知道别人会不会买。挑一个最不确定的点，到现实里问问看。</p><Link to={`/projects/${detail.project.id}/experiment`} className="text-link">准备一项现实挑战 →</Link></section>
    </div></div></>;
}

function VersionSelector({ label, value, versions, onChange }: { label: string; value: string; versions: Version[]; onChange: (id: string) => void }) {
  return <label>{label}<select value={value} onChange={(e) => onChange(e.target.value)}>{versions.map((v, i) => <option key={v.id} value={v.id}>方案 {i + 1} · {v.scene.title}</option>)}</select></label>;
}

function Compare({ detail }: { detail: ProjectDetail }) {
  const versions = detail.versions;
  const [leftId, setLeft] = useState(versions.at(-1)?.parent_version_id ?? versions[0]!.id);
  const [rightId, setRight] = useState(versions.at(-1)!.id);
  const left = versions.find((v) => v.id === leftId)!;
  const right = versions.find((v) => v.id === rightId)!;
  const [leftLabel, setLeftLabel] = useState(defaultLabel(left.scene));
  const [rightLabel, setRightLabel] = useState(defaultLabel(right.scene));
  const [comparison, setComparison] = useState<Comparison>();
  const action = useAction();
  const meta = fieldsFor(left.scene.business_type);
  function pathName(path: string) {
    const field = meta.find((m) => path.startsWith(`fields.${m.key}.`));
    if (field) return field.label + (path.endsWith(".source") ? " · 数据来源" : path.endsWith(".note") ? " · 说明" : "");
    if (path.includes("demand_qty")) return "需求假设";
    return ({ title: "场景名称", period_note: "预演范围", "location.description": "地点描述" } as Record<string, string>)[path] ?? path;
  }
  return <><div className="page-title"><div><p className="eyebrow">换一个选择，会怎样？</p><h1>把两个方案放在一起</h1></div></div>
    {versions.length < 2 ? <div className="empty"><h2>先试一个不同的选择</h2><p>回沙盒改一改备货、价格或时间，再保存为新方案。原方案会保留下来。</p><Link className="button" to={`/projects/${detail.project.id}/play`}>回去试一个新方案</Link></div> : <>
      <form className="card compare-controls" onSubmit={(e) => { e.preventDefault(); void action.run(async () => setComparison(await api.compare(detail.project.id, { left_version_id: leftId, right_version_id: rightId, left_scenario_label: leftLabel, right_scenario_label: rightLabel }))); }}>
        <div><VersionSelector label="左边的方案" value={leftId} versions={versions} onChange={(id) => { setLeft(id); setLeftLabel(defaultLabel(versions.find((v) => v.id === id)!.scene)); setComparison(undefined); }} /><ScenarioSelect scene={left.scene} label={leftLabel} onChange={(v) => { setLeftLabel(v); setComparison(undefined); }} /></div>
        <div><VersionSelector label="右边的方案" value={rightId} versions={versions} onChange={(id) => { setRight(id); setRightLabel(defaultLabel(versions.find((v) => v.id === id)!.scene)); setComparison(undefined); }} /><ScenarioSelect scene={right.scene} label={rightLabel} onChange={(v) => { setRightLabel(v); setComparison(undefined); }} /></div>
        <button disabled={action.pending || leftId === rightId}>{action.pending ? "正在比较……" : "看看有什么不同"}</button>
      </form>{action.error != null && <ErrorCard error={action.error} />}
      {comparison && <section aria-live="polite"><div className="message warning"><strong>先看看比较条件</strong><p>{comparison.same_demand_assumption === null ? "服务按各自的预约与时长条件计算。" : comparison.same_demand_assumption ? "两边采用相同的需求假设。" : "两边需求假设不同，不能只看金额就判断哪个更好。"} {comparison.same_period ? "预演期间相同。" : "预演期间也不同。"}</p><p>{comparison.warning}</p></div>
        <div className="compare-grid"><div><h2>左边的方案</h2><Results calculation={comparison.left} /></div><div><h2>右边的方案</h2><Results calculation={comparison.right} /></div></div>
        <section className="card"><h2>这次改了什么</h2><div className="table-scroll"><table><thead><tr><th>条件</th><th>左边</th><th>右边</th></tr></thead><tbody>{comparison.changed_fields.map((c) => <tr key={c.path}><th>{pathName(c.path)}</th><td>{String(c.left ?? "待确认")}</td><td>{String(c.right ?? "待确认")}</td></tr>)}</tbody></table></div>
          <details><summary>查看未改变的条件和结果差值</summary><pre>{JSON.stringify({ unchanged: comparison.unchanged_fields, deltas: comparison.result_deltas }, null, 2)}</pre></details>
        </section>
      </section>}
    </>}
  </>;
}

function Experiments({ detail }: { detail: ProjectDetail }) {
  const resource = useResource(`summary-${detail.project.id}`, () => api.summary(detail.project.id));
  const action = useAction();
  const observationAction = useAction();
  const [versionId, setVersion] = useState(detail.versions.at(-1)!.id);
  const [question, setQuestion] = useState("");
  const [method, setMethod] = useState("");
  const [taskId, setTask] = useState("");
  const [sample, setSample] = useState("");
  const [observed, setObserved] = useState("");
  const [field, setField] = useState("unit_price_cents");
  const [notes, setNotes] = useState("");
  const [limits, setLimits] = useState("");
  const [notice, setNotice] = useState("");
  const selectedTask = resource.value?.experiments.find((t) => t.id === taskId) ?? resource.value?.experiments[0];
  const taskVersion = detail.versions.find((v) => v.id === selectedTask?.scene_version_id);
  const fields = fieldsFor(taskVersion?.scene.business_type ?? "retail_perishable");
  if (taskVersion?.scene.business_type !== "appointment_service") fields.push({ key: "demand_qty", label: "需求数量", help: "用户自报观察" });
  async function createTask(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      const body = { scene_version_id: versionId, question: question.trim(), method: method.trim(), warnings: [] };
      const task = await api.createTask(detail.project.id, body, action.keyFor("create-task", body));
      setTask(task.id); setQuestion(""); setMethod(""); setNotice("挑战已保存，实际去做后再记录观察。"); resource.reload();
    });
  }
  async function saveObservation(event: FormEvent) {
    event.preventDefault();
    if (!selectedTask) return;
    await observationAction.run(async () => {
      const metadata = fields.find((m) => m.key === field);
      if (!metadata) throw new Error("请先选择要记录的条件");
      const sampleSize = parseQuantity(sample, 1);
      const value = metadata.money ? parseCents(observed) : parseQuantity(observed, metadata.min);
      if (sampleSize === null || value === null) throw new Error("请填写样本量和观察数值");
      const intent = { task: selectedTask.id, field, sampleSize, value, notes, limits };
      // Freeze time for this exact submission intent so a lost response can reuse the same key/body.
      const key = observationAction.keyFor("observation", intent);
      const recordedAt = observationTimes.get(key) ?? new Date().toISOString(); observationTimes.set(key, recordedAt);
      const unit = metadata.money ? "cents" : field.includes("minutes") ? "minutes" : "qty";
      await api.observe(selectedTask.id, { recorded_at: recordedAt, sample_size: sampleSize, notes, limitations: limits, observed_values: { [field]: { value, unit } } }, key);
      setNotes(""); setLimits(""); setObserved(""); setSample(""); setNotice("已保存为你自报的现实观察，不会自动改动原方案。"); resource.reload();
    });
  }
  return <><div className="page-title"><div><p className="eyebrow">从假设，走向一点真实的了解</p><h1>到现实里问问看</h1></div></div>
    <div className="message">从一个小问题开始。先征得同意，不记录姓名或联系方式；小样本不能代表整个市场。</div>
    {notice && <p role="status" className="success">✓ {notice}</p>}
    <div className="experiment-grid"><form className="card" onSubmit={(e) => void createTask(e)}><h2>准备一项小挑战</h2>
      <ExperimentAssistant project={detail.project.id} version={detail.versions.find((v) => v.id === versionId)!} onDraft={(q, m) => { setQuestion(q); setMethod(m); }} />
      <VersionSelector label="关联哪个方案" value={versionId} versions={detail.versions} onChange={setVersion} />
      <label>最想确认的一个问题<input required value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={10000} placeholder="例如：这个价格，对方能接受吗？" /></label>
      <label>打算怎么了解<textarea required rows={4} value={method} onChange={(e) => setMethod(e.target.value)} maxLength={10000} placeholder="写下准备询问谁、如何征得同意，以及如何记录。" /></label>
      <p className="muted">这张卡由你手动填写，不代表已经开展了调查。</p>{action.error != null && <ErrorCard error={action.error} />}<button disabled={action.pending || !question.trim() || !method.trim()}>{action.pending ? "正在保存……" : "保存这项挑战"}</button>
    </form><section className="card"><h2>记下实际观察</h2>
      {resource.error ? <ErrorCard error={resource.error} retry={resource.reload} /> : !resource.value ? <Loading /> : !selectedTask ? <p className="empty">先保存一项挑战，做过之后再来记录。</p> : <form onSubmit={(e) => void saveObservation(e)}>
        <label>这次完成的挑战<select value={selectedTask.id} onChange={(e) => { setTask(e.target.value); setField("unit_price_cents"); setObserved(""); }}>{resource.value.experiments.map((t) => <option key={t.id} value={t.id}>{t.question}</option>)}</select></label>
        <label>记录哪个条件<select value={field} onChange={(e) => { setField(e.target.value); setObserved(""); }}>{fields.map((m) => <option key={m.key} value={m.key}>{m.label}{m.money ? "（元）" : ""}</option>)}</select></label>
        <label>你记录的数值<input required inputMode="decimal" value={observed} onChange={(e) => setObserved(e.target.value)} /></label>
        <label>这次样本有多少个<input required inputMode="numeric" value={sample} onChange={(e) => setSample(e.target.value)} /></label>
        <label>实际观察到了什么<textarea required rows={3} value={notes} maxLength={10000} onChange={(e) => setNotes(e.target.value)} placeholder="只写发生过的事，不必写成漂亮的结论。" /></label>
        <label>这次观察有什么局限<textarea required rows={3} value={limits} maxLength={10000} onChange={(e) => setLimits(e.target.value)} placeholder="例如人数少、只询问熟人、没有真实购买。" /></label>
        <p className="muted">记录时间以本次提交为准；保存后标记为“你记录的现实观察”，不会变为平台核验。</p>
        {observationAction.error != null && <ErrorCard error={observationAction.error} />}<button disabled={observationAction.pending}>{observationAction.pending ? "正在保存……" : "保存这次观察"}</button>
      </form>}
    </section></div>
    {resource.value && <History summary={resource.value} />}
  </>;
}

// Ephemeral intent metadata only. Never stores session tokens or observation content persistently.
const observationTimes = new Map<string, string>();

function History({ summary }: { summary: Summary }) {
  return <section className="card history"><h2>已经记下的观察</h2>{!summary.observations.length ? <p className="muted">这里还没有观察记录。做过之后再填，留空也没关系。</p> : summary.observations.map((o) => <article key={o.id} className="observation"><span className="source user_observation">你记录的现实观察</span><h3>样本量：{o.sample_size}</h3><p>{o.notes}</p><p><strong>局限：</strong>{o.limitations}</p><small>{new Date(o.recorded_at).toLocaleString("zh-CN")}</small></article>)}</section>;
}

function ProjectPage({ id, page, query }: { id: string; page: string; query: URLSearchParams }) {
  const resource = useResource(id, () => api.project(id));
  const detail = resource.value;
  const version = detail?.versions.find((v) => v.id === query.get("version")) ?? detail?.versions.at(-1);
  const example = kinds.find((v) => v === query.get("example"));
  return <main id="main" className="page"><ProjectNav id={id} active={page} />
    {resource.error ? <ErrorCard error={resource.error} retry={resource.reload} /> : !detail ? <Loading />
      : page === "setup" ? <Setup detail={detail} {...(example ? { example } : {})} />
      : !version ? <div className="empty"><h1>先准备一点条件</h1><p>保存场景后，就能亲手试一试了。</p><Link className="button" to={`/projects/${id}/setup`}>去准备场景</Link></div>
      : page === "play" && version.scene.business_type === "retail_perishable" ? <SceneStage key={`${version.id}-${query.get("prepare")}`} detail={detail} version={version} fresh={query.get("prepare") === "1"} {...(query.get("agent_run") ? { initialRun: query.get("agent_run")! } : {})} />
      : page === "play" ? <Sandbox key={version.id} detail={detail} version={version} {...(query.get("agent_run") ? { initialRun: query.get("agent_run")! } : {})} />
      : page === "compare" ? <Compare detail={detail} /> : <Experiments detail={detail} />}
  </main>;
}

export default function App() {
  const [route, setRoute] = useState(location.pathname + location.search);
  useEffect(() => { const update = () => setRoute(location.pathname + location.search); addEventListener("popstate", update); return () => removeEventListener("popstate", update); }, []);
  const [path = "/", search = ""] = route.split("?");
  const match = /^\/projects\/([^/]+)\/(setup|play|compare|experiment)$/.exec(path);
  return <AppBoundary><a className="skip-link" href="#main">跳到主要内容</a><header className="site-header"><Link to="/" className="brand"><span className="brand-mark" aria-hidden="true">未</span><span>未开张<small>BEFORE OPEN</small></span></Link><nav aria-label="主导航"><Link to="/">试一个想法</Link><Link to="/projects">我的想法</Link></nav></header>
    {path === "/" ? <Home /> : path === "/projects" ? <Projects /> : match ? <ProjectPage key={route} id={decodeURIComponent(match[1]!)} page={match[2]!} query={new URLSearchParams(search)} />
      : <main id="main" className="page empty"><h1>这个页面还没有开张</h1><Link className="button" to="/">回到首页</Link></main>}
    <footer className="site-footer">未开张 Before Open <span>探索可能，而不制造确定性。</span></footer>
  </AppBoundary>;
}
