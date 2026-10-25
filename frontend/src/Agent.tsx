import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "./lib/api";
import type { AgentResult, ModelConnection, Scene, Version } from "./lib/types";
import { formatCents } from "./lib/money";
import { defaultLabel, fieldsFor, sourceNames } from "./lib/model";
import { ErrorCard, NumberField, navigate, useAction, useResource } from "./ui";

const providerNames: Record<string, string> = { deepseek: "DeepSeek", openai: "OpenAI", qwen: "通义千问" };

export function ModelConnector() {
  const [open, setOpen] = useState(false);
  const status = useResource("model-status", () => api.models());
  const [provider, setProvider] = useState<ModelConnection["provider"]>("deepseek");
  const [model, setModel] = useState("deepseek-chat");
  const [key, setKey] = useState("");
  const [authorized, setAuthorized] = useState(false);
  const action = useAction();
  function submit(e: FormEvent) {
    e.preventDefault();
    void action.run(async () => {
      try { await api.connectModel({ provider, model, api_key: key, authorize_paid_calls: authorized }); }
      finally { setKey(""); }
      setAuthorized(false); status.reload();
    });
  }
  return <div className="model-connector"><button className="secondary" onClick={() => { setOpen((v) => !v); if (!open) status.reload(); }}>模型接入{status.value?.connected ? ` · ${status.value.model}` : ""}</button>
    {open && <section className="model-panel card" aria-label="模型接入设置"><h2>选择帮你整理想法的模型</h2>
      <p className="muted">模型只理解、选择工具和解释；经营数字仍由同一套公式计算。</p>
      {status.error ? <ErrorCard error={status.error} retry={status.reload} /> : status.value && <>
        {status.value.connected && <div className="message" role="status"><strong>当前已填写：{status.value.model}</strong><p>{status.value.verified ? "已完成过实际模型请求。这里只证明连接可用，不代表模型判断已被现实核验。" : "连接信息已暂存，尚不代表服务或额度已验证。首次实际创建场景时才发起模型请求。"}</p><button className="secondary" onClick={() => void action.run(async () => { await api.disconnectModel(); status.reload(); })}>断开当前模型</button></div>}
        <form onSubmit={submit}><label>模型服务商<select value={provider} onChange={(e) => {
          const next = e.target.value as ModelConnection["provider"]; setProvider(next); setModel(status.value?.available_models[next]?.[0] ?? ""); setKey("");
        }}>{Object.keys(status.value.available_models).map((p) => <option key={p} value={p}>{providerNames[p] ?? p}</option>)}</select></label>
          <label>模型<select value={model} onChange={(e) => setModel(e.target.value)}>{status.value.available_models[provider]?.map((m) => <option key={m} value={m}>{m}</option>)}</select></label>
          <label>你的 API Key<input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} minLength={8} maxLength={512} required /></label>
          <p className="muted">密钥只在当前服务进程内暂存，不写数据库、日志或浏览器持久存储；30分钟内有效，服务重启或断开后需重新填写。请使用可限额的专用密钥。</p>
          <label className="checkbox-label"><input type="checkbox" checked={authorized} onChange={(e) => setAuthorized(e.target.checked)} required />我了解模型可能收费，授权后续主动发起的本轮请求。每轮最多6次模型/工具调度，实际费用以服务商计价为准。</label>
          {action.error != null && <ErrorCard error={action.error} />}<button disabled={action.pending || !authorized || key.length < 8}>{action.pending ? "正在暂存……" : "连接并授权调用"}</button>
        </form>
      </>}
      <button className="secondary" onClick={() => { setOpen(false); setKey(""); }}>收起</button>
    </section>}
  </div>;
}

export function AgentTrace({ run }: { run: AgentResult }) {
  return <details className="agent-trace"><summary>查看真实执行记录（{run.tools?.length ?? 0}次工具执行）</summary>
    <p>状态：{run.status} · 模型：{run.model ?? "未调用"} · 累计调度：{run.total_calls}</p>
    {(run.model_calls ?? []).map((call, i) => <p key={`m${i}`}>模型 · {String(call.operation)} · {String(call.status)} · {String(call.duration_ms)}ms</p>)}
    {(run.tools ?? []).map((tool) => <article key={tool.id} className="trace-item"><strong>{tool.tool_name}</strong> · {tool.status} · {tool.duration_ms}ms
      <small>请求：{tool.request_id ?? "无旧记录编号"} · 方案：{tool.scene_version_id ?? "尚未冻结的草稿"}</small>
      <pre>{JSON.stringify({ input: tool.input_summary, output: tool.output_summary }, null, 2)}</pre></article>)}
  </details>;
}

function FailedRun({ run, project, onUpdate }: { run: AgentResult; project: string; onUpdate: (run: AgentResult) => void }) {
  const action = useAction();
  return <div className="message error" role="alert"><strong>AI这次没有完成</strong><p>{run.message}</p><small>原因：{run.error_code} · 请求：{run.request_id}</small>
    <button disabled={action.pending} className="secondary" onClick={() => void action.run(async () => onUpdate(await api.retryAgent(project, run.id, action.keyFor("retry", [run.id, run.request_id]))))}>{action.pending ? "正在重试……" : "重新确认并重试"}</button>
    {action.error != null && <ErrorCard error={action.error} />}</div>;
}

export function AgentSetup({ project, onUseScene }: { project: string; onUseScene: (scene: Scene) => void }) {
  const [run, setRun] = useState<AgentResult>();
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [invalidFields, setInvalidFields] = useState<Set<string>>(new Set());
  const invalid = invalidFields.size > 0;
  const action = useAction();
  async function clarify(demo: boolean) {
    if (!run) return;
    const body = { run_id: run.id, answers, use_demo_assumptions: demo };
    const result = await api.clarify(project, body, action.keyFor("clarify", body));
    setRun(result); setAnswers({}); setInvalidFields(new Set());
  }
  return <section className="card agent-panel"><div className="section-title"><h2>也可以让智能体帮你准备</h2><span className="source">由你确认后再保存</span></div>
    <p>先在顶部“模型接入”选择服务商并连接。AI只提取原句中的明确事实，未知条件会向你确认。</p>
    <button className="secondary" disabled={action.pending} onClick={() => void action.run(async () => {
      const result = await api.sceneDraft(project, action.keyFor("draft", [project, run?.id])); setRun(result); setAnswers({});
    })}>{action.pending ? "正在执行当前请求……" : run ? "重新准备一份草稿" : "让智能体准备场景"}</button>
    {action.error != null && <ErrorCard error={action.error} />}
    {run && <>
      {run.status === "failed" && <FailedRun run={run} project={project} onUpdate={setRun} />}
      {run.status === "unsupported" && <p className="message warning">{run.message}</p>}
      {run.scene && <><h3>已知和已确认的条件</h3><ul>{Object.entries(run.scene.fields).filter(([, v]) => v.value !== null).map(([key, value]) => <li key={key}>{fieldsFor(run.scene!.business_type).find((m) => m.key === key)?.label ?? key}：{key.endsWith("_cents") ? formatCents(value.value) : value.value} · {sourceNames[value.source]}</li>)}</ul>
        {(run.facts ?? []).map((fact) => <p key={fact.field}>{fact.value} <small>依据：{fact.evidence}</small></p>)}
        {(run.status === "needs_input" || run.status === "needs_confirmation") && <>
          <div className="fields">{(run.questions ?? []).map((q) => <NumberField key={`${run.request_id}-${q.field}`} meta={{ key: q.field, label: q.text, money: q.unit === "元", help: `单位：${q.unit}。不确定可留空。`, ...(q.field === "minutes_per_job" ? { min: 1 } : {}) }} field={{ value: null, source: "unknown", note: "待确认", derived_from: [] }} onChange={(value, error) => {
            setInvalidFields((old) => { const next = new Set(old); if (error) next.add(q.field); else next.delete(q.field); return next; }); setAnswers((old) => { const next = { ...old }; if (value === null) delete next[q.field]; else next[q.field] = value; return next; });
          }} />)}</div>
          <div className="actions"><button disabled={action.pending || invalid || !Object.keys(answers).length} onClick={() => void action.run(() => clarify(false))}>提交这些答案</button><button className="secondary" disabled={action.pending || invalid} onClick={() => void action.run(() => clarify(true))}>未知条件用演示假设继续</button></div>
          {run.status === "needs_confirmation" && <button disabled={action.pending} onClick={() => void action.run(async () => {
            const next = await api.confirmAgent(project, run.id, action.keyFor("confirm-agent", run.id)); setRun(next);
            if (next.scene_version_id) navigate(`/projects/${project}/play?version=${next.scene_version_id}&agent_run=${next.id}`);
          })}>确认这些条件并运行分析</button>}
        </>}
        <details><summary>完整场景与来源</summary><pre>{JSON.stringify(run.scene, null, 2)}</pre></details>
        <button className="secondary" onClick={() => onUseScene(run.scene!)}>把草稿交给我手动调整</button>
      </>}
      <AgentTrace run={run} />
    </>}
  </section>;
}

export function AgentAnalysis({ project, version, label, initialRun }: { project: string; version: Version; label: string; initialRun?: string }) {
  const [run, setRun] = useState<AgentResult>();
  const action = useAction();
  useEffect(() => { let live = true; if (initialRun) api.agent(project, initialRun).then((r) => { if (live) setRun(r); }).catch(() => {}); return () => { live = false; }; }, [project, initialRun]);
  return <section className="card agent-panel"><h2>让智能体看看这个方案</h2><p className="muted">只分析已确认的方案。修改备货等关键条件前，仍会由你选择是否另存。</p>
    <button className="secondary" disabled={action.pending} onClick={() => void action.run(async () => setRun(await api.analyze(project, version.id, label, action.keyFor("analyze", [version.id, label, run?.id]))))}>{action.pending ? "正在运行当前分析……" : "分析当前已保存方案"}</button>
    {action.error != null && <ErrorCard error={action.error} />}
    {run && <>{run.status === "failed" && <FailedRun run={run} project={project} onUpdate={setRun} />}
      {(run.risk_cards ?? []).slice(0, 3).map((card) => <article className={`message ${card.severity === "warning" ? "warning" : ""}`} key={card.type}><p>{card.text}</p><details><summary>查看依据</summary><pre>{JSON.stringify(card.evidence, null, 2)}</pre></details>
        {card.action && run.status === "needs_choice" && <button className="secondary" disabled={action.pending} onClick={() => void action.run(async () => {
          const next = await api.agentAction(project, run.id, card.action!.id, action.keyFor("action", [run.id, card.action!.id])); setRun(next);
          if (next.branch_version_id) navigate(`/projects/${project}/compare`);
        })}>确认：{card.action.label}</button>}</article>)}
      <AgentTrace run={run} />
    </>}
  </section>;
}

export function ExperimentAssistant({ project, version, onDraft }: { project: string; version: Version; onDraft: (question: string, method: string) => void }) {
  const action = useAction();
  const [run, setRun] = useState<AgentResult>();
  return <div className="agent-panel"><button type="button" className="secondary" disabled={action.pending} onClick={() => void action.run(async () => {
    const next = await api.experimentDraft(project, version.id, defaultLabel(version.scene), action.keyFor("experiment", [version.id, run?.id])); setRun(next);
    if (next.experiment_draft) onDraft(next.experiment_draft.question, next.experiment_draft.method);
  })}>{action.pending ? "正在起草……" : "让智能体帮我起草挑战"}</button>
    {action.error != null && <ErrorCard error={action.error} />}
    {run?.status === "failed" && <p role="alert">{run.message}（{run.error_code}）</p>}
    {run?.experiment_draft && <p className="message">仅为草稿，请检查并修改后保存。{run.experiment_draft.warnings.join("；")}</p>}
    {run && <AgentTrace run={run} />}
  </div>;
}
